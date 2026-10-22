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

# TODO: scripts/index/build.py does not exist yet (blocked on spike ADR: retrieval/graph stack)
index:
    uv run python scripts/index/build.py

# TODO: scripts/eval/run.py does not exist yet. Pass `--short` for the CI subset.
eval *args:
    uv run python scripts/eval/run.py {{args}}

# TODO: CLI entry point (src/detective_board/cli.py) does not exist yet
run *args:
    uv run python -m detective_board {{args}}

# Spike benchmarks (exist today). Heavy: needs Ollama; stop other model users first.
bench which="llm":
    uv run python scripts/spike/bench_{{which}}.py
