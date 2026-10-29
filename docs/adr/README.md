# Architecture Decision Records

Format: `0000-template.md` (context, options, decision, consequences). One decision per ADR; amend while Proposed, supersede once Accepted.

| ADR | Title | Status | Provisional? |
|---|---|---|---|
| [0001](0001-repo-and-tooling.md) | Monorepo, Python 3.12, uv, just, ruff, type checker | Accepted (type checker Proposed) | type checker only |
| [0002](0002-storage.md) | Storage: SQLite+FTS5+sqlite-vec, Ladybug / networkx+SQLite | Accepted for storage (SQLite FTS5 + sqlite-vec); graph in SQLite, Ladybug deferred | Ladybug only |
| [0003](0003-mcp.md) | MCP: own `timeline-alibi` + off-the-shelf; `mcp>=2.3,<3` | Proposed | SDK details unverified |
| [0004](0004-symbolic-layer.md) | Symbolic layer: plain Python rules over the graph (R1-R3) | Proposed | effort estimates, engine-dependent parts |
| [0005](0005-web-stack.md) | Web stack: Starlette 1.9.0 + uvicorn 0.54.0, own SSE framing; static ES-module UI, vendored Cytoscape.js 3.34.4 | Accepted | no |
| [0006](0006-embedding-model.md) | Embedding model: bge-m3 | Accepted | retrieval parameters tuned on the same 35 questions |
| [0007](0007-extraction-model.md) | Extraction model: qwen3:4b | Proposed | 12-chunk pilot, AI-written gold |
| [0008](0008-answer-model.md) | Answer model: provisional qwen3:4b | Proposed, finalised after the answer-model check | entirely, until `answers-20261023-082109*` is read |
| [0009](0009-extractive-answers.md) | Extractive answers (model chooses sentences) | Accepted (pilot, n=12) | prompt wording frozen; no human judging |
| [0010](0010-rule-first-answers.md) | Rule-first deterministic answers and the honesty guard | Accepted | hit rate on real graph unmeasured |
| [0011](0011-presence-pass-and-curated-facts.md) | Targeted presence pass and curated demo facts | Accepted (curated facts); Proposed (automatic presence pass) | automatic precision unmeasured; human re-check of curated file done 2026-10-29 |
| [0012](0012-extraction-prompt-v2-1-plus-repair.md) | Generic extraction prompt stays v2.1 plus deterministic repair | Accepted | 12-chunk and 64-chunk samples only |

Not yet written: reranker (not needed for hit@5, see `docs/spike/REPORT.md` section 5).

Related: `docs/spike/db-research.md` (desk research, nothing run), `docs/architecture/c4.md`, `docs/data-schema.md`, `docs/mcp-contracts.md`.
