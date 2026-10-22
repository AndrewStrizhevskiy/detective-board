"""BM25 (FTS5), vector kNN and hybrid RRF search. Hits carry per-arm scores/ranks for tracing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlite_vec

from .embedder import Embedder
from .store import Store


@dataclass
class Hit:
    chunk_id: str
    story: str
    char_start: int  # absolute anchor: (story, char_start, char_end)
    char_end: int
    score: float  # final ordering score (arm score for single-arm search, RRF for hybrid)
    scores: dict[str, float] = field(
        default_factory=dict
    )  # bm25: bm25() (lower=better); vec: distance
    ranks: dict[str, int] = field(default_factory=dict)  # 1-based rank per arm
    text: str = ""


_TOKEN = re.compile(r"\w+", re.UNICODE)
_POSSESSIVE = re.compile(r"['\u2019]s\b")


def fts_query(user_text: str, mode: str = "or") -> str:
    """Turn arbitrary text into a safe FTS5 MATCH expression: every token is a quoted string.

    Quoting neutralises operators (AND/OR/NOT/NEAR), column filters, `*`, `^`, quotes and
    punctuation. A possessive 's is dropped ("Holmes's" -> "Holmes"), otherwise the stray "s"
    token would match almost every chunk; other apostrophes split tokens like the unicode61
    tokenizer does. Returns '' when there is nothing to search for.
    """
    toks = _TOKEN.findall(_POSSESSIVE.sub("", user_text))
    return (" OR " if mode == "or" else " ").join(f'"{t}"' for t in toks)


def _hits(store: Store, rows: list[tuple[int, float]], arm: str) -> list[Hit]:
    out = []
    for rank, (rid, sc) in enumerate(rows, 1):
        c = store.db.execute(
            "SELECT chunk_id, story, char_start, char_end, text FROM chunks WHERE rowid_int=?",
            (rid,),
        ).fetchone()
        out.append(
            Hit(
                c["chunk_id"],
                c["story"],
                c["char_start"],
                c["char_end"],
                sc,
                {arm: sc},
                {arm: rank},
                c["text"],
            )
        )
    return out


def bm25_search(store: Store, query: str, limit: int = 10, mode: str = "or") -> list[Hit]:
    q = fts_query(query, mode)
    if not q:
        return []
    rows = store.db.execute(
        "SELECT rowid, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? "
        "ORDER BY bm25(chunks_fts) LIMIT ?",
        (q, limit),
    ).fetchall()
    return _hits(store, [(r[0], r[1]) for r in rows], "bm25")


def vector_search(store: Store, embedder: Embedder, query: str, limit: int = 10) -> list[Hit]:
    qv = sqlite_vec.serialize_float32(embedder.embed_query(query))
    rows = store.db.execute(
        "SELECT rowid, distance FROM chunk_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (qv, limit),
    ).fetchall()
    return _hits(store, [(r[0], r[1]) for r in rows], "vec")


def rrf_fuse(
    arms: dict[str, list[Hit]],
    k: int = 60,
    weights: dict[str, float] | None = None,
    limit: int | None = None,
) -> list[Hit]:
    """Reciprocal Rank Fusion: score(d) = sum_arm w_arm / (k + rank_arm(d)), ranks 1-based."""
    weights = weights or {}
    fused: dict[str, Hit] = {}
    for arm, hits in arms.items():
        w = weights.get(arm, 1.0)
        for rank, h in enumerate(hits, 1):
            f = fused.get(h.chunk_id)
            if f is None:
                f = fused[h.chunk_id] = Hit(
                    h.chunk_id, h.story, h.char_start, h.char_end, 0.0, text=h.text
                )
            f.score += w / (k + rank)
            f.scores[arm] = h.scores.get(arm, h.score)
            f.ranks[arm] = rank
    ordered = sorted(fused.values(), key=lambda h: (-h.score, h.chunk_id))
    return ordered[:limit] if limit else ordered


def hybrid_search(
    store: Store,
    embedder: Embedder,
    query: str,
    limit: int = 10,
    k: int = 60,
    weights: dict[str, float] | None = None,
    candidates: int = 50,
) -> list[Hit]:
    arms = {
        "bm25": bm25_search(store, query, candidates),
        "vec": vector_search(store, embedder, query, candidates),
    }
    return rrf_fuse(arms, k=k, weights=weights, limit=limit)
