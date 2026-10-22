import json
import math
import sqlite3

import pytest

from detective_board.retrieval import (
    EmbeddingCache,
    EmbeddingConfig,
    HashEmbedder,
    Hit,
    OllamaEmbedder,
    PassThroughReranker,
    Store,
    StoreVersionError,
    bm25_search,
    embed_missing,
    fts_query,
    hybrid_search,
    load_chunks,
    rrf_fuse,
    vector_search,
)

CFG = EmbeddingConfig(model="fake", dim=64, doc_prefix="doc: ", query_prefix="q: ")

TEXTS = [
    "Holmes's violin lay on the table beside the pipe.",
    "Watson wrote of the king of Bohemia and a photograph.",
    "The speckled band was a snake, said Holmes.",
    "A study in scarlet: Lestrade and Gregson disagreed.",
    "Irene Adler outwitted Sherlock Holmes in the end.",
    "It rained on Baker Street all the night long.",
]


@pytest.fixture
def jsonl(tmp_path):
    p = tmp_path / "chunks.jsonl"
    with p.open("w") as f:
        for i, t in enumerate(TEXTS):
            f.write(
                json.dumps(
                    {
                        "chunk_id": f"s{i % 2}-{i:04d}",
                        "story": f"s{i % 2}",
                        "section": "I",
                        "para_start": i,
                        "para_end": i,
                        "char_start": i * 100,
                        "char_end": i * 100 + len(t),
                        "text": t,
                    }
                )
                + "\n"
            )
    return p


@pytest.fixture
def store(jsonl):
    s = Store(":memory:", CFG)
    load_chunks(s, jsonl)
    embed_missing(s, HashEmbedder(CFG))
    return s


def test_extension_and_fts5_available():
    s = Store(":memory:", CFG)
    assert s.db.execute("SELECT vec_version()").fetchone()[0].startswith("v")


@pytest.mark.parametrize(
    "q",
    [
        'Holmes\'s "violin"',
        "AND OR NOT NEAR",
        'text:"x" * ^',
        "(unbalanced",
        '"',
        "-minus +plus",
        "Holmes's",
        "a:b",
        "NEAR(a b)",
        "'; DROP TABLE chunks; --",
    ],
)
def test_fts_escaping_never_raises(store, q):
    bm25_search(store, q)  # must not raise sqlite3.OperationalError


def test_fts_escaping_values():
    assert fts_query("Holmes's") == '"Holmes"'
    assert fts_query("Holmes\u2019s violin", mode="and") == '"Holmes" "violin"'
    assert fts_query('say "hi" AND NOT') == '"say" OR "hi" OR "AND" OR "NOT"'
    assert fts_query("   ... ") == ""
    assert fts_query("a b", mode="and") == '"a" "b"'


def test_bm25_finds_apostrophe_and_empty(store):
    hits = bm25_search(store, "Holmes's violin")
    assert hits[0].chunk_id == "s0-0000"
    assert hits[0].ranks == {"bm25": 1} and "bm25" in hits[0].scores
    assert (hits[0].char_start, hits[0].char_end) == (0, len(TEXTS[0]))
    assert bm25_search(store, "???") == []


def test_idempotent_load(store, jsonl):
    before = store.db.execute("SELECT chunk_id, rowid_int FROM chunks ORDER BY 1").fetchall()
    st = load_chunks(store, jsonl)
    assert (st.inserted, st.updated, st.unchanged) == (0, 0, len(TEXTS))
    assert embed_missing(store, HashEmbedder(CFG)) == 0
    after = store.db.execute("SELECT chunk_id, rowid_int FROM chunks ORDER BY 1").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]
    for t in ("chunks", "chunk_vec"):
        assert store.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == len(TEXTS)
    assert (
        store.db.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH '\"violin\"'"
        ).fetchone()[0]
        == 1
    )


def test_changed_chunk_reembeds_and_reindexes(store, jsonl):
    lines = jsonl.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["text"] = "completely different zeppelin text"
    lines[0] = json.dumps(rec)
    jsonl.write_text("\n".join(lines) + "\n")
    assert load_chunks(store, jsonl).updated == 1
    assert embed_missing(store, HashEmbedder(CFG)) == 1
    assert bm25_search(store, "zeppelin")[0].chunk_id == "s0-0000"
    assert bm25_search(store, "violin") == []


def test_vector_matches_brute_force(store):
    emb = HashEmbedder(CFG)
    q = "Holmes snake band"
    qv = emb.embed_query(q)
    rows = store.db.execute("SELECT chunk_id, text FROM chunks").fetchall()

    def cosdist(a, b):
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        return 1 - sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)

    brute = sorted((cosdist(qv, emb.embed_documents([r["text"]])[0]), r["chunk_id"]) for r in rows)
    got = vector_search(store, emb, q, limit=len(rows))
    assert [h.chunk_id for h in got] == [c for _, c in brute]
    for h, (d, _) in zip(got, brute, strict=True):
        assert h.scores["vec"] == pytest.approx(d, abs=1e-5)
    assert [h.ranks["vec"] for h in got] == list(range(1, len(rows) + 1))


def _h(cid, arm_score=0.0):
    return Hit(cid, "s", 0, 1, arm_score, {"x": arm_score})


def test_rrf_hand_computed():
    a = [_h("A"), _h("B"), _h("C")]
    b = [_h("B"), _h("D"), _h("A")]
    out = rrf_fuse({"bm25": a, "vec": b}, k=60)
    exp = {"A": 1 / 61 + 1 / 63, "B": 1 / 62 + 1 / 61, "C": 1 / 63, "D": 1 / 62}
    assert [h.chunk_id for h in out] == ["B", "A", "D", "C"]
    for h in out:
        assert h.score == pytest.approx(exp[h.chunk_id])
    assert out[0].ranks == {"bm25": 2, "vec": 1}
    # k=1: A = 1/2+1/4 = .75, B = 1/3+1/2 = .8333
    out = rrf_fuse({"bm25": a, "vec": b}, k=1)
    assert out[0].chunk_id == "B" and out[0].score == pytest.approx(5 / 6)
    # weights: bm25 x3, k=0 -> A=3/1+1/3, B=3/2+1/1, C=3/3, D=1/2
    out = rrf_fuse({"bm25": a, "vec": b}, k=0, weights={"bm25": 3.0}, limit=2)
    assert [h.chunk_id for h in out] == ["A", "B"]
    assert out[0].score == pytest.approx(3 + 1 / 3) and out[1].score == pytest.approx(2.5)


def test_hybrid_carries_both_arms(store):
    emb = HashEmbedder(CFG)
    hits = hybrid_search(store, emb, "Holmes violin", limit=3)
    assert hits[0].chunk_id == "s0-0000"
    assert set(hits[0].ranks) == {"bm25", "vec"} and set(hits[0].scores) == {"bm25", "vec"}
    assert PassThroughReranker().rerank("q", hits) is hits


def test_store_version_mismatch(tmp_path):
    p = tmp_path / "db.sqlite"
    Store(p, CFG).close()
    Store(p, CFG).close()  # same config reopens fine
    for bad in (
        EmbeddingConfig("other", 64, "doc: ", "q: "),
        EmbeddingConfig("fake", 32, "doc: ", "q: "),
        EmbeddingConfig("fake", 64, "", "q: "),
    ):
        with pytest.raises(StoreVersionError, match="embed_"):
            Store(p, bad)
    with sqlite3.connect(p) as c:
        c.execute("UPDATE index_manifest SET value='0' WHERE key='schema_version'")
    with pytest.raises(StoreVersionError, match="schema_version"):
        Store(p, CFG)


def test_ollama_embedder_batching_prefix_cache(tmp_path, monkeypatch):
    calls = []
    emb = OllamaEmbedder(CFG, batch_size=2, cache=EmbeddingCache(tmp_path / "c.sqlite"))

    def fake_post(inputs):
        calls.append(list(inputs))
        return [[float(len(s))] * CFG.dim for s in inputs]

    monkeypatch.setattr(emb, "_post", fake_post)
    out = emb.embed_documents(["a", "bb", "ccc"])
    assert calls == [["doc: a", "doc: bb"], ["doc: ccc"]]
    assert out[1][0] == len("doc: bb")
    calls.clear()
    assert emb.embed_documents(["a", "bb", "ccc"]) == out and calls == []  # fully cached
    emb.embed_query("a")
    assert calls == [["q: a"]]  # different prefix => different cache key
