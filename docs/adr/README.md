# Architecture Decision Records

Format: `0000-template.md` (context, options, decision, consequences). One decision per ADR; amend while Proposed, supersede once Accepted.

| ADR | Title | Status | Provisional? |
|---|---|---|---|
| [0001](0001-repo-and-tooling.md) | Monorepo, Python 3.12, uv, just, ruff, type checker | Accepted (type checker Proposed) | type checker only |
| [0002](0002-storage.md) | Storage: SQLite+FTS5+sqlite-vec, Ladybug / networkx+SQLite | Proposed, pending measurement | entirely |
| [0003](0003-mcp.md) | MCP: own `timeline-alibi` + off-the-shelf; `mcp>=2.3,<3` | Proposed | SDK details unverified |

Not yet written, waiting for spike numbers (do not infer decisions from other docs): LLM/model choice, embedding model, reranker.

Related: `docs/spike/db-research.md` (desk research, nothing run), `docs/architecture/c4.md`, `docs/data-schema.md`, `docs/mcp-contracts.md`.
