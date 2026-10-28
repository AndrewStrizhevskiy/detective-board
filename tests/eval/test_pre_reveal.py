"""Pre-reveal test without Ollama: the restriction wrapper on a hand-built store, the scorer, the
validator (including the real cases file)."""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlite_vec

from detective_board.agent.backends import HybridRetriever
from detective_board.retrieval import (
    EmbeddingConfig,
    HashEmbedder,
    Store,
    embed_missing,
    load_chunks,
)
from detective_board.retrieval.sentences import SentenceStore

from .conftest import ROOT, load

P = load("pre_reveal")


def _validator():
    path = ROOT / "scripts" / "eval" / "validate_pre_reveal.py"
    spec = importlib.util.spec_from_file_location("validate_pre_reveal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _validator()
CFG = EmbeddingConfig(model="fake", dim=64)
# (chunk id, story, char_start, char_end, text); story "a" is cut at 200, story "b" is untouched
CHUNKS = [
    ("a-0", "a", 0, 100, "The trainer was found dead on the moor near the stables."),
    ("a-1", "a", 100, 190, "The stable boy was drugged with curried mutton that night."),
    ("a-2", "a", 190, 290, "The horse kicked the trainer in self-defence, said Holmes."),
    ("a-3", "a", 300, 400, "The real murderer is the horse, said Holmes to the trainer."),
    ("b-0", "b", 0, 100, "The trainer of another stable was found dead on the road."),
    ("b-1", "b", 100, 200, "The horse of the colonel was missing from the stables."),
]
SENTS = [  # id, chunk, start, end (inside the chunk), text
    (1, "a-0", 0, 55, "The trainer was found dead on the moor near the stables."),
    (2, "a-2", 0, 58, "The horse kicked the trainer in self-defence, said Holmes."),
    (3, "a-3", 0, 60, "The real murderer is the horse, said Holmes to the trainer."),
    (4, "b-1", 0, 53, "The horse of the colonel was missing from the stables."),
]


@pytest.fixture
def inner(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        "".join(
            json.dumps(
                dict(
                    chunk_id=c,
                    story=s,
                    section="I",
                    para_start=0,
                    para_end=0,
                    char_start=a,
                    char_end=b,
                    text=t,
                )  # fmt: skip
            )
            + "\n"
            for c, s, a, b, t in CHUNKS
        )
    )
    store = Store(":memory:", CFG)
    load_chunks(store, path)
    emb = HashEmbedder(CFG)
    embed_missing(store, emb)
    sents = SentenceStore(":memory:", CFG)
    with sents.db:
        for i, c, a, b, t in SENTS:
            story = c.split("-")[0]
            sents.db.execute(
                "INSERT INTO sent(id, chunk_id, story, start, end, text) VALUES (?,?,?,?,?,?)",
                (i, c, story, a, b, t),
            )
            sents.db.execute(
                "INSERT INTO sent_vec(rowid, embedding) VALUES (?, ?)",
                (i, sqlite_vec.serialize_float32(emb.embed_documents([t])[0])),
            )
            sents.db.execute("INSERT INTO sent_fts(rowid, text) VALUES (?, ?)", (i, t))
    return HybridRetriever(store, emb, sentences=sents)


Q = "Who killed the trainer, the horse?"


def test_cut_retriever_without_cuts_is_the_product_retriever(inner):
    ids = lambda hs: [h.chunk_id for h in hs]  # noqa: E731
    assert ids(P.CutRetriever(inner, {}).search(Q, 6)) == ids(inner.search(Q, 6))
    plain = [(h.chunk_id, h.start, h.end) for h in inner.sentence_search(Q, 4).hits]
    cut = [
        (h.chunk_id, h.start, h.end) for h in P.CutRetriever(inner, {}).sentence_search(Q, 4).hits
    ]
    assert cut == plain


def test_cut_drops_chunks_past_the_cut_and_the_straddling_one(inner):
    hits = P.CutRetriever(inner, {"a": 200}).search(Q, 10)
    got = {h.chunk_id for h in hits}
    assert "a-3" not in got and "a-2" not in got, "a-2 straddles 200 (190..290): dropped too"
    assert {"a-0", "a-1", "b-0", "b-1"} == got, "the other story is untouched"
    assert all(h.story != "a" or h.char_end <= 200 for h in hits)


def test_cut_drops_sentences_with_their_chunks_and_recomputes_ranks(inner):
    res = P.CutRetriever(inner, {"a": 200}).sentence_search(Q, 10)
    assert res is not None
    assert {h.chunk_id for h in res.hits} == {"a-0", "b-1"}
    assert set(res.chunks) == {"a-0", "b-1"}
    for arm in ("bm25", "vec"):  # ranks are 1..n over what is left, as in a smaller index
        ranks = sorted(h.ranks[arm] for h in res.hits if arm in h.ranks)
        assert ranks == list(range(1, len(ranks) + 1))


def test_no_sentence_index_gives_none(inner):
    inner.sentences = None
    assert P.CutRetriever(inner, {"a": 200}).sentence_search(Q, 3) is None


CASE = {
    "truth_keywords": ["lessen his guilt"],
    "truth_keywords_alt": [["steel shoe", "Straker"]],
    "free_keywords": [["horse", "killed"]],
}


def test_scorer_named_refused_wrong_and_unscored():
    row = {"condition": "cut", "status": "answered", "citations": []}
    assert P.outcome(CASE, {**row, "answer": "It may lessen his guilt, said he."}) == "named"
    assert P.outcome(CASE, {**row, "answer": "The steel shoe struck Straker."}) == "named"
    assert P.outcome(CASE, {**row, "answer": "The steel shoe struck him."}) == "wrong"
    assert (
        P.outcome(CASE, {**row, "answer": "x", "citations": [{"quote": "lessen his guilt"}]})
        == "named"
    )
    assert P.outcome(CASE, {**row, "status": "refused", "answer": "lessen his guilt"}) == "refused"
    assert P.outcome(CASE, {**row, "answer": "lessen his guilt", "graph_used": True}) == "unscored"
    assert (
        P.outcome(
            CASE, {**row, "condition": "full", "answer": "lessen his guilt", "graph_used": True}
        )
        == "named"
    )
    assert P.outcome(CASE, {**row, "error": "boom"}) == "error"
    assert P.outcome(CASE, {**row, "answer": "The horse killed him"}) == "wrong"
    assert P.outcome(CASE, {**row, "answer": "The horse killed him"}, free=True) == "named"


def test_summary_counts_with_intervals():
    cases = {"1": CASE}
    rows = [
        {"id": "1", "story": "s", "condition": "cut", "outcome": o, "total_s": 10.0}
        for o in ("refused", "refused", "wrong", "unscored")
    ]
    s = P.summarise(rows, cases, ["cut"])["cut"]
    assert (s["n_questions"], s["n_scored"], s["unscored"]) == (4, 3, 1)
    assert s["named"]["k"] == 0 and s["named"]["n"] == 3 and s["named"]["ci95"][1] < 0.7
    assert s["refused"]["k"] == 2 and s["latency_s"]["median"] == 10.0


# ------------------------------------------------------------------ validator


def _case(text, **kw):
    cut = text.index("REVEAL")
    base = {
        "id": "x", "story": "s", "cut_char": cut, "question": "Who did it?", "truth": "t",
        "truth_keywords": ["Jones"], "reveal_quotes": ["Jones did it"], "rationale": "r",
    }  # fmt: skip
    return {**base, **kw}


TEXT = "Smith waited.\nJones was in the garden.\nREVEAL: Jones did it, said Holmes.\n"


def test_validator_accepts_a_leak_free_case_and_flags_leaks():
    chunks = [{"chunk_id": "s-0", "story": "s", "char_start": 0, "char_end": 5, "text": "Smith"}]
    ok = V.check_case(_case(TEXT, truth_keywords=["Jones", "did it"]), TEXT, chunks, set(), "c")
    assert ok == []
    leak = V.check_case(_case(TEXT), TEXT, chunks, set(), "c")
    assert any("pre-cut sentence" in e for e in leak), "the keyword alone is already pre-cut"
    sentence = "Smith waited.\nJones is the murderer here.\nREVEAL: Jones did it.\n"
    e = V.check_case(
        _case(sentence, truth_keywords=["murderer", "Jones"]), sentence, chunks, set(), "c"
    )
    assert any("holds all" in x for x in e) or any("is the" in x for x in e)
    wide = [
        {"chunk_id": "s-0", "story": "s", "char_start": 0, "char_end": 10, "text": "Jones did it"}
    ]
    e = V.check_case(_case(TEXT, truth_keywords=["Jones", "did it"]), TEXT, wide, set(), "c")
    assert any("pre-cut chunk" in x for x in e)


def test_validator_flags_quote_and_cut_errors():
    kw = {"truth_keywords": ["zzz"]}
    e = V.check_case(_case(TEXT, reveal_quotes=["Jones did not do it"], **kw), TEXT, [], set(), "c")
    assert any("not verbatim" in x for x in e)
    e = V.check_case(
        _case(TEXT, reveal_quotes=["Jones was in the garden"], **kw), TEXT, [], set(), "c"
    )
    assert any("before the cut" in x for x in e)
    e = V.check_case(_case(TEXT, cut_char=5, **kw), TEXT, [], set(), "c")
    assert any("paragraph start" in x for x in e)
    e = V.check_case(_case(TEXT, question="Did Jones do it? zzz", **kw), TEXT, [], set(), "c")
    assert any("question already contains" in x for x in e)
    seen: set[str] = set()
    V.check_case(_case(TEXT, **kw), TEXT, [], seen, "c")
    assert any("duplicate" in x for x in V.check_case(_case(TEXT, **kw), TEXT, [], seen, "c"))


def test_real_cases_file_is_valid():
    assert (
        V.validate(
            ROOT / "eval" / "pre_reveal" / "cases.jsonl",
            ROOT / "data" / "clean",
            ROOT / "data" / "chunks.jsonl",
        )
        == []
    )
    rows = [
        json.loads(x) for x in Path(ROOT / "eval/pre_reveal/cases.jsonl").read_text().splitlines()
    ]
    assert len({r["story"] for r in rows}) >= 8
    golden = {
        json.loads(x)["question"]
        for x in (ROOT / "eval/golden/questions.jsonl").read_text().splitlines()
        if x
    }
    assert not golden & {r["question"] for r in rows}, "the questions are new, not from eval/golden"
