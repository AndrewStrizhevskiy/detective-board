"""SQLite DDL and migrations for the graph (docs/data-schema.md 3.4, authoritative fallback form).

Versioning: `PRAGMA user_version`. `migrate()` applies every missing step in order, inside one
transaction each, and refuses a database that is newer than this code.
"""

from __future__ import annotations

import sqlite3

GRAPH_BUILD_VERSION = (
    "3"  # bump when resolution/derivation logic changes (invalidates input hashes)
)

_V1 = """
CREATE TABLE g_chunk (
  chunk_id   TEXT PRIMARY KEY,
  story      TEXT NOT NULL,
  char_start INTEGER NOT NULL,
  char_end   INTEGER NOT NULL,
  contiguous INTEGER NOT NULL DEFAULT 1,
  text_sha   TEXT NOT NULL,
  input_hash TEXT NOT NULL            -- hash of chunk text + extraction + build versions
);
CREATE INDEX g_chunk_story ON g_chunk(story, char_start);

CREATE TABLE g_node (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('person','place','item','event','claim')),
  story TEXT NOT NULL,
  name TEXT,                           -- display name (entities); NULL for event/claim
  norm_name TEXT,                      -- normalised key (entities)
  unnamed INTEGER NOT NULL DEFAULT 0,  -- person without a proper name ("the deceased")
  props_json TEXT NOT NULL,            -- aliases, description, time_text, time_norm, content, ...
  provenance TEXT NOT NULL DEFAULT 'extracted' CHECK (provenance IN ('extracted','derived')),
  confidence TEXT NOT NULL DEFAULT 'high' CHECK (confidence IN ('high','low')),
  conf_reason TEXT,
  -- anchor of event/claim nodes (entities use g_mention)
  chunk_id TEXT REFERENCES g_chunk(chunk_id),
  char_start INTEGER, char_end INTEGER, rel_start INTEGER, rel_end INTEGER,
  quote TEXT, ambiguous INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX g_node_name ON g_node(story, name);
CREATE INDEX g_node_kind ON g_node(story, kind);
CREATE INDEX g_node_chunk ON g_node(chunk_id);

CREATE TABLE g_edge (
  id INTEGER PRIMARY KEY,
  src TEXT NOT NULL REFERENCES g_node(id),
  dst TEXT NOT NULL REFERENCES g_node(id),
  rel TEXT NOT NULL,
  props_json TEXT,
  provenance TEXT NOT NULL DEFAULT 'extracted' CHECK (provenance IN ('extracted','derived')),
  confidence TEXT NOT NULL DEFAULT 'high' CHECK (confidence IN ('high','low')),
  chunk_id TEXT NOT NULL REFERENCES g_chunk(chunk_id),
  char_start INTEGER, char_end INTEGER, rel_start INTEGER, rel_end INTEGER,
  quote TEXT NOT NULL, ambiguous INTEGER NOT NULL DEFAULT 0,
  UNIQUE (src, dst, rel, chunk_id, rel_start, rel_end)
);
CREATE INDEX g_edge_src ON g_edge(src, rel);
CREATE INDEX g_edge_dst ON g_edge(dst, rel);
CREATE INDEX g_edge_chunk ON g_edge(chunk_id);

-- One row per surface form of an entity in a chunk; carries the entity's anchor in that chunk.
CREATE TABLE g_mention (
  id INTEGER PRIMARY KEY,
  node_id TEXT NOT NULL REFERENCES g_node(id),
  chunk_id TEXT NOT NULL REFERENCES g_chunk(chunk_id),
  surface TEXT NOT NULL,
  surface_norm TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('name','alias','descr')),  -- descr: unnamed, never matched
  implicit INTEGER NOT NULL DEFAULT 0,   -- created from an event/claim reference, no entity item
  char_start INTEGER, char_end INTEGER, rel_start INTEGER NOT NULL, rel_end INTEGER NOT NULL,
  quote TEXT NOT NULL, ambiguous INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX g_mention_node ON g_mention(node_id);
CREATE INDEX g_mention_norm ON g_mention(surface_norm, role);
CREATE INDEX g_mention_chunk ON g_mention(chunk_id);

-- Items dropped or flagged during ingest (audit; data-schema 3.3 grounding failures).
CREATE TABLE g_dropped (
  chunk_id TEXT NOT NULL REFERENCES g_chunk(chunk_id),
  item_kind TEXT NOT NULL, idx INTEGER NOT NULL, reason TEXT NOT NULL, quote TEXT,
  PRIMARY KEY (chunk_id, item_kind, idx, reason)
);

-- Curation / normaliser results that survive re-ingest: story_day for events, structured claim
-- `prop` (docs/symbolic-layer.md 1.2). Keyed by node id (ids are stable per chunk and index).
CREATE TABLE g_overlay (
  node_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'low' CHECK (confidence IN ('high','low')),
  source TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (node_id, key)
);

CREATE TABLE g_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

MIGRATIONS: list[str] = [_V1]
LATEST = len(MIGRATIONS)


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Bring `conn` to the latest schema; returns the final version."""
    cur = schema_version(conn)
    if cur > LATEST:
        raise RuntimeError(f"graph database schema v{cur} is newer than supported v{LATEST}")
    for v in range(cur, LATEST):
        # executescript commits first; user_version is set in the same script so a failed step
        # leaves the previous version in place.
        try:
            conn.executescript(f"BEGIN;\n{MIGRATIONS[v]}\nPRAGMA user_version = {v + 1};\nCOMMIT;")
        except sqlite3.Error:
            conn.rollback()
            raise
    return schema_version(conn)
