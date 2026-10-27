"""Build (or resume) the sentence index: data/index/sentences.sqlite.

    uv run python -m detective_board.index.sentences [--chunks data/chunks.jsonl]
        [--out data/index/sentences.sqlite] [--batch 32] [--cache data/cache/sentences-emb.sqlite]

Every chunk of the chunk file is split into sentences (retrieval.sentences.split_sentences); the
rows and the FTS index are written in ONE transaction, then the vectors are embedded in batches
(bge-m3 through Ollama, no prefixes; a per-text on-disk cache makes a killed run resume where it
stopped, and a rebuild of the same sentences costs no embedding). Idempotent: when the file is
complete for the same chunk file, splitter and embedding identity, nothing is touched. A changed
chunk file or splitter rebuilds the sentence rows (the embedding cache still serves unchanged
texts). Progress goes to stderr, the summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from detective_board.index.build import CONFIG
from detective_board.retrieval import Embedder, EmbeddingCache, EmbeddingConfig, OllamaEmbedder
from detective_board.retrieval.sentences import (
    SPLITTER_VERSION,
    SentenceStore,
    chunks_digest,
    embed_text,
    iter_sentences,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNKS = ROOT / "data" / "chunks.jsonl"
OUT = ROOT / "data" / "index" / "sentences.sqlite"
CACHE = ROOT / "data" / "cache" / "sentences-emb.sqlite"


@dataclass
class SentenceBuildReport:
    out: str
    chunks: int = 0
    sentences: int = 0
    vectors: int = 0
    embedded: int = 0  # vectors computed in this run (cache hits included)
    rebuilt_rows: bool = False
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.sentences > 0 and self.sentences == self.vectors

    def render(self) -> str:
        return (
            f"sentence index {self.out}\n"
            f"chunks {self.chunks}, sentences {self.sentences}, vectors {self.vectors} "
            f"(new in this run {self.embedded}, rows rebuilt {self.rebuilt_rows}), "
            f"{self.seconds:.1f}s\n" + ("OK" if self.ok else "PROBLEM: counts disagree")
        )


def _load_chunks(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_sentences(
    chunks_path: str | Path = CHUNKS,
    out: str | Path = OUT,
    embedder: Embedder | None = None,
    cfg: EmbeddingConfig = CONFIG,
    batch: int = 32,
    progress: Callable[[str], None] | None = None,
) -> SentenceBuildReport:
    t0 = time.monotonic()
    say = progress or (lambda s: print(s, file=sys.stderr, flush=True))
    out = Path(out)
    if str(out) != ":memory:":
        out.parent.mkdir(parents=True, exist_ok=True)
    chunks = _load_chunks(Path(chunks_path))
    digest = chunks_digest(chunks_path)
    rep = SentenceBuildReport(out=str(out), chunks=len(chunks))
    with SentenceStore(out, cfg) as st:
        db = st.db
        meta = st.manifest()
        fresh = meta.get("chunks_sha256") == digest and meta.get("splitter") == SPLITTER_VERSION
        # the splitter version is written at creation; a stale file keeps the old one
        if not fresh or db.execute("SELECT count(*) FROM sent").fetchone()[0] == 0:
            rows = [(i, *s) for i, s in enumerate(iter_sentences(chunks), 1)]
            with db:
                db.execute("DELETE FROM sent_vec")
                db.execute("DELETE FROM sent")
                db.executemany(
                    "INSERT INTO sent(id, chunk_id, story, start, end, text) VALUES (?,?,?,?,?,?)",
                    rows,
                )
                db.execute("INSERT INTO sent_fts(sent_fts) VALUES('rebuild')")
                db.executemany(
                    "INSERT OR REPLACE INTO sent_manifest(key, value) VALUES (?, ?)",
                    {
                        "chunks_sha256": digest,
                        "splitter": SPLITTER_VERSION,
                        "min_words": "4",
                        "complete": "0",
                    }.items(),
                )
            rep.rebuilt_rows = True
            say(f"sentences: {len(rows)} from {len(chunks)} chunks")
        todo = db.execute(
            "SELECT id, text FROM sent WHERE id NOT IN (SELECT rowid FROM sent_vec) ORDER BY id"
        ).fetchall()
        total = db.execute("SELECT count(*) FROM sent").fetchone()[0]
        if todo and embedder is None:
            embedder = OllamaEmbedder(cfg, batch_size=batch)
        for s in range(0, len(todo), batch):
            part = todo[s : s + batch]
            vecs = (embedder or _unreachable()).embed_documents(
                [embed_text(r["text"]) for r in part]
            )
            with db:
                db.executemany(
                    "INSERT INTO sent_vec(rowid, embedding) VALUES (?, ?)",
                    [
                        (r["id"], sqlite_vec.serialize_float32(v))
                        for r, v in zip(part, vecs, strict=True)
                    ],
                )
            rep.embedded += len(part)
            done = total - len(todo) + s + len(part)
            el = time.monotonic() - t0
            eta = el / rep.embedded * (len(todo) - rep.embedded)
            say(f"embedded {done}/{total} ({el:.0f}s elapsed, eta {eta:.0f}s)")
        rep.sentences = total
        rep.vectors = db.execute("SELECT count(*) FROM sent_vec").fetchone()[0]
        if rep.ok:
            st.set_manifest(complete="1", sentences=str(total))
    rep.seconds = time.monotonic() - t0
    return rep


def _unreachable() -> Embedder:  # pragma: no cover - guarded by `todo`
    raise RuntimeError("no embedder")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build data/index/sentences.sqlite (resumable)")
    ap.add_argument("--chunks", type=Path, default=CHUNKS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--cache", type=Path, default=CACHE, help="on-disk embedding cache")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    a = ap.parse_args(argv)
    a.cache.parent.mkdir(parents=True, exist_ok=True)
    cache = EmbeddingCache(a.cache)
    emb = OllamaEmbedder(
        CONFIG, base_url=a.ollama_url, batch_size=a.batch, cache=cache, keep_alive="30m"
    )
    rep = build_sentences(a.chunks, a.out, emb, CONFIG, a.batch)
    print(rep.render())
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
