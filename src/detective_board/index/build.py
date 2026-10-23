"""Build (or refresh) the real index. Idempotent: a second run changes nothing.

    uv run python -m detective_board.index.build

Vectors are taken from the spike embedding cache (data/cache/emb/<model>-<sha>.jsonl, one JSON line
per chunk: {"id", "h": sha1(doc_prefix + text)[:12], "v"}) whenever the text hash still matches;
only chunks without a valid cached vector are sent to Ollama. Cached vectors are L2-normalised on
import (cosine metric). Nothing is embedded when the cache is complete, so Ollama is not needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import sqlite_vec

from detective_board.retrieval import (
    Embedder,
    EmbeddingConfig,
    OllamaEmbedder,
    Store,
    embed_missing,
    load_chunks,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNKS = ROOT / "data" / "chunks.jsonl"
DB = ROOT / "data" / "index" / "db.sqlite"
EMB_CACHE_DIR = ROOT / "data" / "cache" / "emb"

CONFIG = EmbeddingConfig(model="bge-m3", dim=1024, doc_prefix="", query_prefix="", metric="cosine")
# Settings the spike cache was written with (scripts/spike/bench_retrieval.cache_path).
SPIKE_NUM_CTX, SPIKE_TRUNCATE = 2048, True


def spike_cache_path(cfg: EmbeddingConfig, cache_dir: Path = EMB_CACHE_DIR) -> Path:
    """Same file name the spike benchmark derives from model + doc prefix + num_ctx + truncate."""
    settings = json.dumps(
        {"doc_prefix": cfg.doc_prefix, "num_ctx": SPIKE_NUM_CTX, "truncate": SPIKE_TRUNCATE},
        sort_keys=True,
        ensure_ascii=False,
    )
    sha = hashlib.sha1(settings.encode("utf-8")).hexdigest()[:10]
    return cache_dir / f"{re.sub(r'[^A-Za-z0-9._-]', '_', cfg.model)}-{sha}.jsonl"


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _read_cache(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                out[r["id"]] = {"h": r["h"], "v": r["v"]}
            except (json.JSONDecodeError, KeyError):
                continue  # torn last line of an interrupted write
    return out


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    if not n or not math.isfinite(n):
        raise ValueError("zero or non-finite embedding in cache")
    return [x / n for x in v]


def import_cached_vectors(store: Store, cache_file: Path) -> tuple[int, int]:
    """Insert cached vectors for chunks that have none. Returns (imported, stale_or_missing).
    A cached vector is used only if its text hash matches the chunk's current text."""
    cache = _read_cache(cache_file)
    dim, prefix = store.cfg.dim, store.cfg.doc_prefix
    rows = store.db.execute(
        "SELECT chunk_id, rowid_int, text FROM chunks "
        "WHERE rowid_int NOT IN (SELECT rowid FROM chunk_vec) ORDER BY rowid_int"
    ).fetchall()
    todo: list[tuple[int, bytes]] = []
    stale = 0
    for r in rows:
        e = cache.get(r["chunk_id"])
        if e is None or e["h"] != text_hash(prefix + r["text"]):
            stale += 1
            continue
        if len(e["v"]) != dim:
            raise ValueError(
                f"cached vector for {r['chunk_id']} has dim {len(e['v'])}, config says {dim}"
            )
        todo.append((r["rowid_int"], sqlite_vec.serialize_float32(_unit(e["v"]))))
    with store.db:
        store.db.executemany("INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)", todo)
    return len(todo), stale


@dataclass
class BuildReport:
    db: str
    chunks_file: int = 0
    chunks: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    vectors: int = 0
    vectors_from_cache: int = 0
    vectors_embedded: int = 0
    fts_rows: int = 0
    per_story: dict[str, int] = field(default_factory=dict)
    manifest: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        lines = [
            f"index   {self.db}",
            f"chunks  {self.chunks} in db / {self.chunks_file} in file "
            f"(inserted {self.inserted}, updated {self.updated}, unchanged {self.unchanged})",
            f"vectors {self.vectors} (from cache {self.vectors_from_cache}, "
            f"embedded {self.vectors_embedded})",
            f"fts     {self.fts_rows} rows",
            f"stories {len(self.per_story)}: "
            + ", ".join(f"{s}={n}" for s, n in sorted(self.per_story.items())),
            "manifest " + ", ".join(f"{k}={v}" for k, v in sorted(self.manifest.items())),
        ]
        lines += [f"PROBLEM {p}" for p in self.problems] or ["OK: counts agree"]
        return "\n".join(lines)


def _count_lines(path: Path) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def build_index(
    db_path: str | Path = DB,
    chunks_path: str | Path = CHUNKS,
    cfg: EmbeddingConfig = CONFIG,
    cache_file: Path | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> BuildReport:
    """Load chunks, import cached vectors, embed whatever is still missing, verify counts."""
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    cache_file = cache_file or spike_cache_path(cfg)
    rep = BuildReport(db=str(db_path), chunks_file=_count_lines(Path(chunks_path)))
    with Store(db_path, cfg) as store:
        st = load_chunks(store, chunks_path)
        rep.inserted, rep.updated, rep.unchanged = st.inserted, st.updated, st.unchanged
        rep.vectors_from_cache, _ = import_cached_vectors(store, cache_file)
        missing = store.db.execute(
            "SELECT count(*) FROM chunks WHERE rowid_int NOT IN (SELECT rowid FROM chunk_vec)"
        ).fetchone()[0]
        if missing:
            factory = embedder_factory or (lambda: OllamaEmbedder(cfg))
            rep.vectors_embedded = embed_missing(store, factory())
        db = store.db
        rep.chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
        rep.vectors = db.execute("SELECT count(*) FROM chunk_vec").fetchone()[0]
        rep.fts_rows = db.execute("SELECT count(*) FROM chunks_fts_docsize").fetchone()[0]
        rep.per_story = {
            r[0]: r[1] for r in db.execute("SELECT story, count(*) FROM chunks GROUP BY story")
        }
        rep.manifest = store.manifest()
        if not (rep.chunks == rep.chunks_file == rep.vectors == rep.fts_rows):
            rep.problems.append(
                f"count mismatch: file={rep.chunks_file} chunks={rep.chunks} "
                f"vectors={rep.vectors} fts={rep.fts_rows}"
            )
        try:
            db.execute("INSERT INTO chunks_fts(chunks_fts, rank) VALUES('integrity-check', 1)")
        except Exception as e:  # sqlite3.DatabaseError: index out of sync with content table
            rep.problems.append(f"fts integrity-check failed: {e}")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build data/index/db.sqlite from data/chunks.jsonl")
    ap.add_argument("--chunks", type=Path, default=CHUNKS)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--emb-cache", type=Path, default=None, help="spike embedding cache file")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    a = ap.parse_args(argv)
    rep = build_index(
        a.db,
        a.chunks,
        cache_file=a.emb_cache,
        embedder_factory=lambda: OllamaEmbedder(CONFIG, base_url=a.ollama_url),
    )
    print(rep.render())
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
