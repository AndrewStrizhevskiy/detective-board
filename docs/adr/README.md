# Architecture Decision Records

Format: `0000-template.md` (context, options, decision, consequences). One decision per ADR; amend while Proposed, supersede once Accepted.

| ADR | Title | Status | Provisional? |
|---|---|---|---|
| [0001](0001-repo-and-tooling.md) | Monorepo, Python 3.12, uv, just, ruff, type checker | Accepted (type checker Proposed) | type checker only |
| [0002](0002-storage.md) | Storage: SQLite+FTS5+sqlite-vec, Ladybug / networkx+SQLite | Proposed, pending measurement | entirely |
| [0003](0003-mcp.md) | MCP: own `timeline-alibi` + off-the-shelf; `mcp>=2.3,<3` | Proposed | SDK details unverified |
| [0004](0004-symbolic-layer.md) | Symbolic layer: plain Python rules over the graph (R1-R3) | Proposed | effort estimates, engine-dependent parts |
| [0005](0005-web-stack.md) | Web stack: Starlette 1.9.0 + uvicorn 0.54.0, own SSE framing; static ES-module UI, vendored Cytoscape.js 3.34.4 | Accepted | no |

Not yet written, waiting for spike numbers (do not infer decisions from other docs): LLM/model choice, embedding model, reranker.

Related: `docs/spike/db-research.md` (desk research, nothing run), `docs/architecture/c4.md`, `docs/data-schema.md`, `docs/mcp-contracts.md`.
