# ADR-0006: Embedding model

- Status: **Accepted**
- Date: 2026-10-23
- Deciders: tech-lead
- Provisional parts: none for the choice. The retrieval parameters (RRF k=30, BM25 weight 0.5 against vector 1) were tuned on the same 35 questions they are scored on, so their numbers are optimistic. Evidence: `docs/spike/REPORT.md` sections 4 and 5.

## Context

The corpus is English (596 chunks); users may ask in Russian (the customer and the demo audience). Embeddings run through Ollama on a CPU-only i7-8665U with 15 GiB RAM, offline. The index is built once and cached. Candidates already in Ollama: bge-m3, nomic-embed-text, snowflake-arctic-embed, all-minilm.

## Options (measured, `docs/spike/results/`)

Chunk-level retrieval on 35 questions (`retrieval-20261023-*.md`), speed on 50 chunks per pass (`embed-20261022-*.md`):

| Model | dim | chunks/s | peak RSS MiB | hit@1 | hit@5 | hit@10 | MRR | Russian hit@5 (n=5) |
|---|---|---|---|---|---|---|---|---|
| bge-m3 | 1024 | 0.46 | 2076 | 0.57 | 0.89 | 0.94 | 0.70 | 1.00 |
| nomic-embed-text | 768 | 1.29-1.31 | 457 | 0.43 | 0.69 | 0.74 | 0.53 | 0.00 |
| snowflake-arctic-embed | 1024 | 0.49 | 780 | 0.26 | 0.63 | 0.69 | 0.41 | 0.00 |
| all-minilm | 384 | 9.36 | 172 | 0.26 | 0.46 | 0.51 | 0.35 | 0.00 |

Story-level smoke test (n=15 EN, n=5 RU): all models reach 0.93-1.00 on English; Russian hit@5 is 1.00 for bge-m3 and 0.00-0.20 for the others.

## Decision

Use **bge-m3** (1024 dimensions, no query/document prefixes) through Ollama, with hybrid retrieval: FTS5 BM25 (OR mode) fused with the vector arm by RRF, k=30, weights bm25:vector = 0.5:1 (`arms-20261023-080849.md`: hit@5 0.97 hybrid against 0.89 vector-only and 0.69 BM25-only). The model identity stays configuration (`retrieval/config.py`), so it can be replaced by re-indexing.

Reasons: it is the best English model on chunk-level hit@5 (0.89 against 0.46-0.69) and the only one that retrieves from Russian questions. Indexing 596 chunks takes about 22 minutes (596 / 0.46 chunks/s) once, and the embedding runner needs about 2.1 GB RSS.

What would reverse it: a larger question set in which another model matches bge-m3 on English and a Russian requirement is dropped; or an indexing or RAM budget that excludes 22 minutes and 2.1 GB.

## Consequences

- Russian retrieval works only through the vector arm: BM25 returns an empty list for Russian queries (5 of 5). Hybrid equals vector-only for Russian.
- The index must be rebuilt (about 22 min, cached by `EmbeddingCache`) if the model, chunking or text normalisation changes.
- The embedding runner and the LLM runner must not be loaded together during measurements; they fit in RAM together for normal use (about 2.1 + 3.5 GiB with a 4B model).
- Re-tune k and weights on a held-out question set before quoting 0.97 as a result.
- No reranker is adopted: only hit@1 has headroom (REPORT section 5).
