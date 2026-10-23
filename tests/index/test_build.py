import json

import pytest

from detective_board.index.build import (
    build_index,
    import_cached_vectors,
    spike_cache_path,
    text_hash,
)
from detective_board.retrieval import EmbeddingConfig, HashEmbedder, Store

CFG = EmbeddingConfig(model="fake", dim=16)
TEXTS = ["Holmes lit his pipe.", "Watson wrote it down.", "The band was a snake."]


@pytest.fixture
def jsonl(tmp_path):
    p = tmp_path / "chunks.jsonl"
    with p.open("w") as f:
        for i, t in enumerate(TEXTS):
            rec = {
                "chunk_id": f"s-{i:04d}",
                "story": "s",
                "section": "I",
                "para_start": i,
                "para_end": i,
                "char_start": i * 50,
                "char_end": i * 50 + len(t),
                "text": t,
            }
            f.write(json.dumps(rec) + "\n")
    return p


def write_cache(path, texts, skip=(), bad_hash=(), dim=16):
    emb = HashEmbedder(EmbeddingConfig(model="fake", dim=dim))
    with path.open("w") as f:
        for i, t in enumerate(texts):
            if i in skip:
                continue
            h = "deadbeef0000" if i in bad_hash else text_hash(t)
            v = [x * 3.0 for x in emb.embed_documents([t])[0]]  # unnormalised on purpose
            f.write(json.dumps({"id": f"s-{i:04d}", "h": h, "v": v}) + "\n")


class CountingEmbedder(HashEmbedder):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.seen: list[str] = []

    def embed_documents(self, texts):
        self.seen += list(texts)
        return super().embed_documents(texts)


def test_complete_cache_needs_no_embedder(tmp_path, jsonl):
    cache = tmp_path / "c.jsonl"
    write_cache(cache, TEXTS)

    def boom():
        raise AssertionError("embedder must not be created")

    rep = build_index(tmp_path / "i" / "db.sqlite", jsonl, CFG, cache, boom)
    assert rep.ok, rep.problems
    assert (rep.chunks, rep.vectors, rep.fts_rows) == (3, 3, 3)
    assert (rep.vectors_from_cache, rep.vectors_embedded) == (3, 0)
    assert "OK" in rep.render()


def test_stale_and_missing_vectors_are_embedded(tmp_path, jsonl):
    cache = tmp_path / "c.jsonl"
    write_cache(cache, TEXTS, skip={0}, bad_hash={1})
    emb = CountingEmbedder(CFG)
    rep = build_index(tmp_path / "db.sqlite", jsonl, CFG, cache, lambda: emb)
    assert rep.ok
    assert (rep.vectors_from_cache, rep.vectors_embedded) == (1, 2)
    assert sorted(emb.seen) == sorted(TEXTS[:2])


def test_idempotent(tmp_path, jsonl):
    cache = tmp_path / "c.jsonl"
    write_cache(cache, TEXTS)
    db = tmp_path / "db.sqlite"
    build_index(db, jsonl, CFG, cache)
    again = build_index(db, jsonl, CFG, cache, lambda: pytest.fail("no embedding expected"))
    assert again.ok
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 3)
    assert (again.vectors_from_cache, again.vectors_embedded) == (0, 0)
    assert (again.chunks, again.vectors, again.fts_rows) == (3, 3, 3)


def test_imported_vectors_are_unit_length_and_searchable(tmp_path, jsonl):
    cache = tmp_path / "c.jsonl"
    write_cache(cache, TEXTS)
    db = tmp_path / "db.sqlite"
    build_index(db, jsonl, CFG, cache)
    from detective_board.retrieval import hybrid_search

    with Store(db, CFG) as store:
        hits = hybrid_search(store, HashEmbedder(CFG), "snake band", limit=1)
    assert hits[0].chunk_id == "s-0002"


def test_dimension_mismatch_raises(tmp_path, jsonl):
    cache = tmp_path / "c.jsonl"
    write_cache(cache, TEXTS, dim=8)
    with Store(tmp_path / "db.sqlite", CFG) as store:
        from detective_board.retrieval import load_chunks

        load_chunks(store, jsonl)
        with pytest.raises(ValueError, match="dim 8"):
            import_cached_vectors(store, cache)


def test_torn_cache_line_is_ignored(tmp_path, jsonl):
    cache = tmp_path / "c.jsonl"
    write_cache(cache, TEXTS)
    with cache.open("a") as f:
        f.write('{"id": "s-0000", "h": "x')  # interrupted write
    rep = build_index(tmp_path / "db.sqlite", jsonl, CFG, cache)
    assert rep.ok and rep.vectors_from_cache == 3


def test_spike_cache_path_matches_existing_file():
    cfg = EmbeddingConfig(model="bge-m3", dim=1024)
    assert spike_cache_path(cfg).name == "bge-m3-6d617e1982.jsonl"
