"""Idempotent ingest of data/chunks.jsonl and embedding of missing vectors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from .embedder import Embedder
from .store import Store

_FIELDS = (
    "chunk_id",
    "story",
    "section",
    "para_start",
    "para_end",
    "char_start",
    "char_end",
    "text",
)


@dataclass
class LoadStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


def load_chunks(store: Store, jsonl: str | Path) -> LoadStats:
    """Upsert chunks. Re-running on the same file changes nothing; changed text drops its vector."""
    db, stats = store.db, LoadStats()
    with db:
        nxt = db.execute("SELECT COALESCE(MAX(rowid_int), 0) + 1 FROM chunks").fetchone()[0]
        with open(jsonl, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                row = tuple(rec[k] for k in _FIELDS)
                old = db.execute(
                    f"SELECT {', '.join(_FIELDS)}, rowid_int FROM chunks WHERE chunk_id=?",
                    (rec["chunk_id"],),
                ).fetchone()
                if old is None:
                    db.execute(
                        f"INSERT INTO chunks({', '.join(_FIELDS)}, rowid_int) VALUES ({'?,' * 8}?)",
                        (*row, nxt),
                    )
                    nxt += 1
                    stats.inserted += 1
                elif tuple(old)[:-1] == row:
                    stats.unchanged += 1
                else:
                    sets = ", ".join(f"{k}=?" for k in _FIELDS[1:])
                    db.execute(
                        f"UPDATE chunks SET {sets} WHERE chunk_id=?", (*row[1:], rec["chunk_id"])
                    )
                    db.execute("DELETE FROM chunk_vec WHERE rowid=?", (old["rowid_int"],))
                    stats.updated += 1
        if stats.inserted or stats.updated:
            db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    return stats


def embed_missing(store: Store, embedder: Embedder, batch: int = 64) -> int:
    """Embed chunks that have no vector yet. Safe to re-run / resume."""
    db = store.db
    missing = db.execute(
        "SELECT rowid_int, text FROM chunks WHERE rowid_int NOT IN (SELECT rowid FROM chunk_vec) "
        "ORDER BY rowid_int"
    ).fetchall()
    for s in range(0, len(missing), batch):
        part = missing[s : s + batch]
        vecs = embedder.embed_documents([r["text"] for r in part])
        with db:
            db.executemany(
                "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                [
                    (r["rowid_int"], sqlite_vec.serialize_float32(v))
                    for r, v in zip(part, vecs, strict=True)
                ],
            )
    return len(missing)
