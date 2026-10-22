# ADR-0001: Monorepo, Python 3.12, uv, just, ruff, type checker

- Status: Accepted for monorepo, Python, uv, just, ruff (already in the repo). Proposed for the type checker.
- Date: 2026-10-22
- Deciders: tech-lead
- Provisional parts: type checker (pyright vs mypy) not yet chosen.

## Context

Local CPU-only GraphRAG agent, one team, one deployable. Target machine: Python 3.12.3, Linux x86_64 (db-research.md). The repo already has `pyproject.toml` (`requires-python >=3.12`, ruff line-length 100, pytest marker `live`), `uv.lock` and a `justfile` (`lint`, `test`). Components (indexing pipeline, agent core, API, MCP servers) share data models (`Extraction`, anchors, trace events), so splitting repos would force versioned cross-repo contracts for no gain.

## Options

1. Monorepo, single Python package `detective_board` with subpackages (`extract`, `contracts`, `mcp`, ...); UI in a sibling directory in the same repo [P: UI location].
2. Multi-repo (backend, UI, MCP servers): independent releases, but contract drift and a heavier workflow for a small team.
3. Tooling: `uv` (lockfile, venv) vs pip+pip-tools/poetry; `just` vs make; `ruff` (lint+format) vs flake8+black.
4. Type checker: `pyright` vs `mypy`. Not measured; no experiment run. Pydantic v2 models are used heavily; both support them (mypy via plugin **[U]**).

## Decision

- Monorepo, one Python package, Python 3.12 (`>=3.12`, CI and docs assume 3.12).
- `uv` for environments and the lockfile; dependencies pinned exactly in `uv.lock`; `mcp` and `sqlite-vec` pinned exactly (see ADR-0002/0003).
- `just` is the single entry point (`just lint`, `just test`; extend with `just index`, `just eval`).
- `ruff check` and `ruff format` (line length 100) are mandatory in `just lint`.
- Type checker: proposed `pyright` in basic mode on `src/`, because of faster feedback with pydantic; final pick deferred until the first run on real code. Whichever is chosen runs in `just lint`; only one is kept.

## Consequences

- One lockfile, one CI job; contract stubs in `src/detective_board/contracts/` are imported directly by all components.
- UI toolchain (Node) adds a second package manager inside the repo; keep it isolated in its own directory.
- If the type-checker choice changes, this ADR is amended (not a new ADR) until it is Accepted.
