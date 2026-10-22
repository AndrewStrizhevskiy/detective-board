# ADR-0002: Storage (vectors, BM25, graph)

- Status: **Proposed, pending measurement**
- Date: 2026-10-22
- Deciders: tech-lead
- Provisional parts: ALL of it. Nothing below was installed or benchmarked; evidence is desk research only (`docs/spike/db-research.md`). Embedding model (vector dimension, quality) is undecided and is not covered here.

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

## Decision (provisional)

- Retrieval: one SQLite file with FTS5 (BM25) and `sqlite-vec` pinned `==0.1.9`, RRF fusion in Python, behind `VectorStore` and `Bm25Store` interfaces. Fallback: LanceDB, triggered if sqlite-vec fails the recall/latency gate in the eval.
- Graph: Ladybug behind a `GraphStore` adapter, with `networkx + SQLite` as the fallback and as the schema of record (`g_node`/`g_edge` in `docs/data-schema.md`). Because the SQLite form is the source of truth, the adapter can be swapped without re-extraction.
- Kuzu is not selected; the tech-lead/graph-engineer agent text mentioning it as candidate should be updated when this ADR is accepted.
- The decision is confirmed (status -> Accepted) only after Phase 1 measures: Ladybug install size/RAM and variable-length path queries on our schema; sqlite-vec recall@k and latency against an exact baseline on the eval set; sqlite-vec Python helper API; FTS5 vs `bm25s` retrieval quality. Measurements are blocked until the running benchmarks finish.

## Consequences

- Single-file index, trivially offline and reproducible; interface seams limit lock-in.
- Risk concentrated in two young dependencies (sqlite-vec, Ladybug); both pinned, both with a named fallback.
- Graph written as SQLite first costs a load step into Ladybug if chosen; accepted for the safety.
- Reranker choice and embedding choice are separate decisions awaiting spike numbers; no ADR is written for them yet.
