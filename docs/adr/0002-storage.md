# ADR-0002: Storage (vectors, BM25, graph)

- Status: **Accepted for storage (SQLite FTS5 + sqlite-vec)**. Graph store: SQLite, as built; Ladybug deferred.
- Date: 2026-10-22, updated 2026-10-23
- Deciders: tech-lead
- Provisional parts: Ladybug stays unverified and deferred (nothing installed). sqlite-vec was not benchmarked against an exact baseline for recall, only used in the retrieval benchmarks (`docs/spike/results/arms-20261023-080849.md`); it remains pre-v1 and pinned. Embedding model: see ADR-0006.

## Context

Corpus: 20 Holmes stories, 596 chunks today (tens of thousands at most). Needs: dense + lexical retrieval with fusion, phrase/NEAR search for verifying quotes, a small graph (entities, events, claims, relations with source anchors), offline, embedded, CPU-only, low RAM. The earlier agent definition lists Kuzu as a graph candidate; Kuzu was archived by its owner on 2025-10-10 (last release `kuzu` 0.11.3), so it must not be the long-term choice.

## Options

Vectors / BM25:
1. SQLite + FTS5 (system SQLite 3.45.1, FTS5 present) + `sqlite-vec` 0.1.9 (~160 KB, MIT/Apache-2.0). Pros: tiny, one file, phrase/NEAR. Cons: sqlite-vec is pre-v1 ("expect breaking changes"), helper API and ANN vs brute-force status unverified, FTS5 BM25 params fixed.
2. LanceDB 0.40.0 (Apache-2.0, 71 MB wheel + pyarrow): built-in hybrid and rerank hooks, scales; heavy, fast-moving 0.x.
3. Chroma, Qdrant local: rejected in desk research (heavy tree / dev-test mode).
4. `bm25s` 0.3.14 as lexical comparison arm (tunable k1/b); `rank-bm25` dropped (unmaintained).

Graph:
1. Ladybug `ladybug` 0.21.2 (MIT, 9 MB, Cypher, active Kuzu continuation). Unverified: Kuzu API/on-disk compat, variable-length path syntax, install footprint.
2. networkx 3.7 + SQLite tables (BSD, no engine risk, no Cypher; temporal/claim queries hand-written in SQL). Fine for a small graph; in-memory when loaded, unmeasured.
3. `kuzu==0.11.3` frozen: stable but unmaintained.
4. FalkorDBLite (SSPL engine, Redis subprocess, beta) and DuckDB+DuckPGQ (online extension install): rejected.

## Decision

Update 2026-10-23: confirmed by working code and tests.

- Retrieval: one SQLite file with FTS5 (`chunks_fts`) and `sqlite-vec` pinned `==0.1.9` (`vec0` table `chunk_vec`), RRF fusion in Python (`src/detective_board/retrieval/store.py`, `search.py`; `pyproject.toml`). Hybrid retrieval on 35 questions with bge-m3 reaches hit@5 0.97 against 0.89 vector-only and 0.69 BM25-only (`arms-20261023-080849.md`; parameters tuned on the same questions). The LanceDB fallback was not needed and is not built. `bm25s` was not used as a comparison arm; FTS5 BM25 is the lexical arm.
- Graph: **SQLite is the store, as built** (`src/detective_board/graph/store.py`, standard library `sqlite3`, `g_node`/`g_edge` per `docs/data-schema.md`). Neither Ladybug nor networkx is imported anywhere in `src/` or listed in `pyproject.toml`; graph queries and path searches are written against SQLite, and the symbolic rules (ADR-0004) read facts from it. **Ladybug is deferred**, not rejected: revisit only if SQLite graph queries become a measured bottleneck or Cypher is needed. The `GraphStore` seam from the original decision is kept so that a swap does not require re-extraction.
- Kuzu is not selected. The agent text that names Kuzu as a candidate should be updated.

What would reverse it: sqlite-vec failing a recall or latency gate on a larger corpus (then LanceDB), or SQLite graph queries failing to meet latency on the demo graph (then Ladybug).

## Consequences

- Single-file index, trivially offline and reproducible; interface seams limit lock-in.
- Risk is concentrated in one young dependency, sqlite-vec (pinned, with LanceDB as named fallback). The graph has no engine dependency.
- Moving the graph to Ladybug later costs a load step from SQLite; accepted.
- Embedding model: ADR-0006. No reranker is adopted (REPORT section 5).
