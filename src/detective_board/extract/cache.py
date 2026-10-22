"""On-disk cache of raw model outputs (SQLite, WAL, one commit per put: append-safe, resumable).

Key = sha256(chunk text + model + prompt version + schema version + generation options).
Parsing/grounding are re-run on every read, so changing them never needs a new LLM call.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def cache_key(
    text: str, model: str, prompt_version: str, schema_version: str, options: dict[str, Any]
) -> str:
    blob = json.dumps(
        [text, model, prompt_version, schema_version, options],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ExtractCache:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS raw (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.conn.commit()

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT value FROM raw WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO raw(key, value) VALUES (?,?)",
            (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()

    def __len__(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM raw").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
