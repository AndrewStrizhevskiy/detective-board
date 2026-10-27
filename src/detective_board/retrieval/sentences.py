"""Sentence-level hybrid index: the same chunks, split into sentences, searched by BM25 + vector.

The chunk index answers "which passage"; the extractive answer mode needs "which sentence", and a
lexical scorer over the top chunks cannot find a sentence that shares no word with the question
(a Russian question over English text). This module keeps a separate SQLite file (default
data/index/sentences.sqlite) with one row per sentence:

    sent(id, chunk_id, story, start, end, text)   chunk.text[start:end] == text, exactly
    sent_fts                                       FTS5 over text, tokenizer as the chunk FTS
    sent_vec                                       vec0 float[dim], cosine, rowid = sent.id
    sent_manifest                                  versions, embedding identity, chunk-file hash

Splitting reuses `agent.window.sentence_spans` (one definition of "sentence" for the whole
project). Short sentences are NEVER dropped: a unit of fewer than MIN_WORDS words (`"Yes."`,
`"Holmes!"`, a bare dialogue tag) is merged with the FOLLOWING sentence (with the previous one
when it is the last of the chunk), so the pair stays one contiguous slice of the chunk text with
exact offsets and the answer keeps its context. Only a chunk that has fewer than MIN_WORDS words
in total yields no sentence. Embedding input is the text with whitespace collapsed (the stored
text keeps the original characters), without any prefix, like the chunk index.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import sqlite_vec

from detective_board.agent.window import sentence_spans

from .config import EmbeddingConfig
from .search import Hit, fts_query, rrf_fuse

SENT_SCHEMA_VERSION = "1"
SPLITTER_VERSION = "window.sentence_spans+merge4-1"
MIN_WORDS = 4
# Same constants as the chunk search (eval/evidence_in_prompt.RRF).
RRF_K = 30
RRF_WEIGHTS = {"bm25": 0.5, "vec": 1.0}
_META_PREFIX = "embed_"


class SentenceIndexError(RuntimeError):
    """The sentence index file is incompatible with the code or the embedding configuration."""


def split_sentences(text: str, min_words: int = MIN_WORDS) -> list[tuple[int, int]]:
    """(start, end) offsets in `text` of the indexed sentences; text[start:end] is the sentence.

    Units shorter than `min_words` words are merged into the next unit (the previous one at the
    end of the text); see the module docstring."""
    spans = sentence_spans(text)
    out: list[tuple[int, int]] = []
    pend: int | None = None  # start of a short unit waiting for its successor
    for a, b in spans:
        if pend is not None:
            a = pend
            pend = None
        if len(text[a:b].split()) < min_words:
            pend = a
            continue
        out.append((a, b))
    if pend is not None:  # trailing short unit: glue it to the previous sentence
        b = spans[-1][1]
        if out:
            out[-1] = (out[-1][0], b)
        elif len(text[pend:b].split()) >= min_words:
            out.append((pend, b))
    return out


def embed_text(text: str) -> str:
    return " ".join(text.split())


def chunks_digest(chunks_path: str | Path) -> str:
    """sha256 over the chunk file bytes: a changed corpus invalidates the sentence index."""
    h = hashlib.sha256()
    with open(chunks_path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _ddl(cfg: EmbeddingConfig) -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS sent (
          id       INTEGER PRIMARY KEY,
          chunk_id TEXT NOT NULL,
          story    TEXT NOT NULL,
          start    INTEGER NOT NULL,
          end      INTEGER NOT NULL,
          text     TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS sent_chunk ON sent(chunk_id, start)",
        """CREATE VIRTUAL TABLE IF NOT EXISTS sent_fts USING fts5(
          text, content='sent', content_rowid='id', tokenize='porter unicode61')""",
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS sent_vec USING vec0(
          embedding float[{cfg.dim}] distance_metric={cfg.metric})""",
        "CREATE TABLE IF NOT EXISTS sent_manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ]


class SentenceStore:
    """Open (or create) a sentence index. `path` may be ':memory:'."""

    def __init__(self, path: str | Path, cfg: EmbeddingConfig):
        self.cfg = cfg
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        have = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='sent_manifest'").fetchone()
        if have:
            self._check_manifest()
        with self.db:
            for stmt in _ddl(cfg):
                self.db.execute(stmt)
            if not have:
                rows = {"schema_version": SENT_SCHEMA_VERSION, "splitter": SPLITTER_VERSION}
                rows |= {_META_PREFIX + k: v for k, v in cfg.as_meta().items()}
                self.db.executemany(
                    "INSERT INTO sent_manifest(key, value) VALUES (?, ?)", rows.items()
                )

    def _check_manifest(self) -> None:
        meta = self.manifest()
        problems = []
        if meta.get("schema_version") != SENT_SCHEMA_VERSION:
            problems.append(f"schema_version {meta.get('schema_version')!r}")
        for k, v in self.cfg.as_meta().items():
            if meta.get(_META_PREFIX + k) != v:
                problems.append(
                    f"{_META_PREFIX}{k} store={meta.get(_META_PREFIX + k)!r} config={v!r}"
                )
        if problems:
            raise SentenceIndexError(
                "sentence index was built with a different configuration ("
                + "; ".join(problems)
                + "). Rebuild it with `python -m detective_board.index.sentences`."
            )

    def manifest(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.db.execute("SELECT * FROM sent_manifest")}

    def set_manifest(self, **kv: str) -> None:
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO sent_manifest(key, value) VALUES (?, ?)", kv.items()
            )

    def count(self) -> int:
        return self.db.execute("SELECT count(*) FROM sent").fetchone()[0]

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> SentenceStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass
class SentenceHit:
    id: int
    chunk_id: str
    story: str
    start: int  # offsets inside the chunk text: chunk.text[start:end] == text
    end: int
    text: str
    score: float  # RRF
    ranks: dict[str, int] = field(default_factory=dict)  # 1-based per arm
    scores: dict[str, float] = field(default_factory=dict)  # bm25: bm25() (lower=better); vec: dist


def _key(rowid: int) -> str:
    return f"{rowid:012d}"  # fixed width: rrf_fuse breaks ties on this string


def _arm(store: SentenceStore, rows: Sequence[tuple[int, float]], arm: str) -> list[Hit]:
    out = []
    for rank, (rid, sc) in enumerate(rows, 1):
        r = store.db.execute(
            "SELECT story, start, end, text FROM sent WHERE id=?", (rid,)
        ).fetchone()
        out.append(
            Hit(_key(rid), r["story"], r["start"], r["end"], sc, {arm: sc}, {arm: rank}, r["text"])
        )
    return out


def sentence_bm25(store: SentenceStore, query_text: str, limit: int) -> list[Hit]:
    q = fts_query(query_text, "or")
    if not q or limit <= 0:
        return []
    rows = store.db.execute(
        "SELECT rowid, bm25(sent_fts) FROM sent_fts WHERE sent_fts MATCH ? "
        "ORDER BY bm25(sent_fts) LIMIT ?",
        (q, limit),
    ).fetchall()
    return _arm(store, [(r[0], r[1]) for r in rows], "bm25")


def sentence_vector(store: SentenceStore, query_vector: Sequence[float], limit: int) -> list[Hit]:
    if limit <= 0:
        return []
    rows = store.db.execute(
        "SELECT rowid, distance FROM sent_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (sqlite_vec.serialize_float32(list(query_vector)), limit),
    ).fetchall()
    return _arm(store, [(r[0], r[1]) for r in rows], "vec")


def sentence_search(
    store: SentenceStore,
    query_text: str,
    query_vector: Sequence[float] | None,
    k_vec: int = 50,
    k_bm25: int = 50,
    k: int = 12,
) -> list[SentenceHit]:
    """Hybrid RRF over sentences (k=30, bm25:vec 0.5:1, BM25 in OR mode); the best `k` hits.

    `query_vector` is the already computed query embedding (None = BM25 only)."""
    arms = {
        "bm25": sentence_bm25(store, query_text, k_bm25),
        "vec": sentence_vector(store, query_vector, k_vec) if query_vector is not None else [],
    }
    fused = rrf_fuse(arms, k=RRF_K, weights=RRF_WEIGHTS, limit=k)
    out = []
    for h in fused:
        rid = int(h.chunk_id)
        r = store.db.execute("SELECT chunk_id FROM sent WHERE id=?", (rid,)).fetchone()
        out.append(
            SentenceHit(
                rid,
                r["chunk_id"],
                h.story,
                h.char_start,
                h.char_end,
                h.text,
                h.score,
                h.ranks,
                h.scores,
            )  # fmt: skip
        )
    return out


def iter_sentences(chunks: Iterable[dict]) -> Iterable[tuple[str, str, int, int, str]]:
    """(chunk_id, story, start, end, text) for every sentence of every chunk, in file order."""
    for c in chunks:
        t = c["text"]
        for a, b in split_sentences(t):
            yield c["chunk_id"], c["story"], a, b, t[a:b]
