"""SQLite store: chunks + FTS5 (BM25) + sqlite-vec (vec0) + manifest."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from .config import EmbeddingConfig

SCHEMA_VERSION = "1"
_META_PREFIX = "embed_"


class StoreVersionError(RuntimeError):
    """Existing store was built with an incompatible schema or embedding config."""


def _ddl(cfg: EmbeddingConfig) -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS chunks (
          chunk_id   TEXT PRIMARY KEY,
          rowid_int  INTEGER UNIQUE NOT NULL,
          story      TEXT NOT NULL,
          section    TEXT NOT NULL,
          para_start INTEGER NOT NULL,
          para_end   INTEGER NOT NULL,
          char_start INTEGER NOT NULL,
          char_end   INTEGER NOT NULL,
          text       TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS chunks_story ON chunks(story, char_start)",
        """CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          text, content='chunks', content_rowid='rowid_int',
          tokenize='porter unicode61')""",
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(
          embedding float[{cfg.dim}] distance_metric={cfg.metric})""",
        """CREATE TABLE IF NOT EXISTS index_manifest (
          key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    ]


class Store:
    """Open (or create) an index file. `path` may be ':memory:'."""

    def __init__(self, path: str | Path, cfg: EmbeddingConfig):
        self.cfg = cfg
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self._open()

    def _open(self) -> None:
        have = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='index_manifest'").fetchone()
        if have:
            self._check_manifest()
        with self.db:
            for stmt in _ddl(self.cfg):
                self.db.execute(stmt)
            if not have:
                rows = {"schema_version": SCHEMA_VERSION}
                rows |= {_META_PREFIX + k: v for k, v in self.cfg.as_meta().items()}
                self.db.executemany(
                    "INSERT INTO index_manifest(key, value) VALUES (?, ?)", rows.items()
                )

    def _check_manifest(self) -> None:
        meta = self.manifest()
        problems = []
        if meta.get("schema_version") != SCHEMA_VERSION:
            problems.append(
                f"schema_version store={meta.get('schema_version')!r} code={SCHEMA_VERSION!r}"
            )
        for k, v in self.cfg.as_meta().items():
            got = meta.get(_META_PREFIX + k)
            if got != v:
                problems.append(f"{_META_PREFIX}{k} store={got!r} config={v!r}")
        if problems:
            raise StoreVersionError(
                "index was built with a different configuration ("
                + "; ".join(problems)
                + "). Rebuild the index or fix the config."
            )

    def manifest(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.db.execute("SELECT * FROM index_manifest")}

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
