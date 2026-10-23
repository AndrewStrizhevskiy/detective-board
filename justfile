set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Create env with dev tools (first run needs network; later runs work offline)
setup:
    uv sync --group dev
    @echo "optional: uvx pre-commit install"

lint:
    uv run ruff check . && uv run ruff format --check .

fmt:
    uv run ruff check --fix . && uv run ruff format .

typecheck:
    uv run pyright

# Fast, deterministic suite (no Ollama)
test:
    uv run pytest -m "not live and not e2e"

# CI variant with coverage gate on core
test-cov:
    uv run pytest -m "not live and not e2e" --cov --cov-report=term-missing --cov-fail-under=80

# Needs a running Ollama + pulled models; never run in CI
test-live:
    uv run pytest -m live

# Build data/index/db.sqlite (chunks + FTS5 + bge-m3 vectors). Needs Ollama with bge-m3 unless
# vectors are cached in data/cache/emb (about 22 min on the target laptop, once).
index:
    uv run python -m detective_board.index.build

# TODO: scripts/eval/run.py does not exist yet. Pass `--short` for the CI subset.
eval *args:
    uv run python scripts/eval/run.py {{args}}

# Web UI + API on http://127.0.0.1:8000. Use `just run --fake` for canned demo data without Ollama.
# Full wiring to the real index/graph/MCP: see docs/api.md and docs/HANDOFF.md (open items).
run *args:
    uv run python -m detective_board.api {{args}}

# Spike benchmarks (exist today). Heavy: needs Ollama; stop other model users first.
bench which="llm":
    uv run python scripts/spike/bench_{{which}}.py

# UI logic tests (node built-in runner; 2 live tests skip without DB_URL)
test-web:
    node --test tests/web_js/*.test.mjs
