import json

import pytest

from detective_board.index.sentences import build_sentences
from detective_board.retrieval import EmbeddingConfig, HashEmbedder
from detective_board.retrieval.sentences import SentenceStore, sentence_search

CFG = EmbeddingConfig(model="fake", dim=16)
TEXTS = [
    "Holmes lit his pipe. He said nothing for a long while. Then he rose.",
    "Watson wrote it all down in his notebook that night. “Yes.” The case was closed.",
]


class Counting(HashEmbedder):
    def __init__(self, cfg, fail_after=None):
        super().__init__(cfg)
        self.seen: list[str] = []
        self.fail_after = fail_after

    def embed_documents(self, texts):
        if self.fail_after is not None and len(self.seen) >= self.fail_after:
            raise ConnectionError("ollama went away")
        self.seen += list(texts)
        return super().embed_documents(texts)


@pytest.fixture
def jsonl(tmp_path):
    p = tmp_path / "chunks.jsonl"
    with p.open("w") as f:
        for i, t in enumerate(TEXTS):
            f.write(json.dumps({"chunk_id": f"s-{i:04d}", "story": "s", "text": t}) + "\n")
    return p


def snapshot(path):
    with SentenceStore(path, CFG) as st:
        rows = [tuple(r) for r in st.db.execute("SELECT * FROM sent ORDER BY id")]
        vecs = st.db.execute("SELECT rowid, embedding FROM sent_vec ORDER BY rowid").fetchall()
        return rows, [(r[0], bytes(r[1])) for r in vecs], st.manifest()


def test_build_counts_offsets_and_manifest(tmp_path, jsonl):
    out = tmp_path / "s.sqlite"
    emb = Counting(CFG)
    rep = build_sentences(jsonl, out, emb, CFG, batch=2, progress=lambda s: None)
    assert rep.ok and rep.chunks == 2 and rep.sentences == rep.vectors == len(emb.seen) == 4
    rows, vecs, meta = snapshot(out)
    assert len(vecs) == 4
    for _, cid, _, a, b, text in rows:
        assert TEXTS[int(cid[-1])][a:b] == text
    assert any("“Yes.” The case was closed." in r[5] for r in rows)  # short unit merged forward
    assert meta["complete"] == "1" and meta["sentences"] == "4"
    assert meta["embed_model"] == "fake" and meta["embed_dim"] == "16"
    with SentenceStore(out, CFG) as st:
        q = HashEmbedder(CFG).embed_query("Holmes lit his pipe")
        assert sentence_search(st, "pipe", q, 5, 5, 1)[0].text == "Holmes lit his pipe."


def test_idempotent_second_run_changes_nothing(tmp_path, jsonl):
    out = tmp_path / "s.sqlite"
    build_sentences(jsonl, out, Counting(CFG), CFG, 2, progress=lambda s: None)
    before = snapshot(out)
    emb = Counting(CFG)
    rep = build_sentences(jsonl, out, emb, CFG, 2, progress=lambda s: None)
    assert emb.seen == [] and rep.embedded == 0 and not rep.rebuilt_rows and rep.ok
    assert snapshot(out) == before


def test_resumes_after_a_crash_and_embeds_only_the_rest(tmp_path, jsonl):
    out = tmp_path / "s.sqlite"
    with pytest.raises(ConnectionError):
        build_sentences(jsonl, out, Counting(CFG, fail_after=2), CFG, 2, progress=lambda s: None)
    with SentenceStore(out, CFG) as st:
        assert st.count() == 4 and st.manifest()["complete"] == "0"
        assert st.db.execute("SELECT count(*) FROM sent_vec").fetchone()[0] == 2
    emb = Counting(CFG)
    rep = build_sentences(jsonl, out, emb, CFG, 2, progress=lambda s: None)
    assert len(emb.seen) == 2 and rep.ok and not rep.rebuilt_rows
    full = tmp_path / "full.sqlite"
    build_sentences(jsonl, full, Counting(CFG), CFG, 2, progress=lambda s: None)
    assert snapshot(out) == snapshot(full)


def test_changed_chunk_file_rebuilds_rows(tmp_path, jsonl):
    out = tmp_path / "s.sqlite"
    build_sentences(jsonl, out, Counting(CFG), CFG, 2, progress=lambda s: None)
    with jsonl.open("a") as f:
        f.write(
            json.dumps({"chunk_id": "s-0002", "story": "s", "text": "A new chunk of text."}) + "\n"
        )
    rep = build_sentences(jsonl, out, Counting(CFG), CFG, 2, progress=lambda s: None)
    assert rep.rebuilt_rows and rep.sentences == rep.vectors == 5 and rep.ok
