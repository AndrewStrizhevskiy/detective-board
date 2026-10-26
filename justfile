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

# Build data/graph/graph.sqlite from the extraction cache(s) and normalise it. Resumable (cache hits).
# Optional shard caches are merged into data/cache/extract-cache.sqlite first, for example:
#   just graph qwen3:4b 20 "data/cache/extract-cache-qwen3_4b-shard*.sqlite"
# Needs Ollama only for chunks that are not in the cache.
graph model="qwen3:4b" stories="20" caches="":
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p data/cache data/graph
    if [ -n "{{caches}}" ]; then
        uv run python scripts/merge_extract_cache.py merge data/cache/extract-cache.sqlite {{caches}} --model {{model}}
    fi
    scripts/run_extraction_priority.sh {{model}} {{stories}}
    uv run python -m detective_board.extract.normalise data/graph/graph.sqlite

# Add normalised times and claim propositions to the graph (graph already built).
normalise:
    uv run python -m detective_board.extract.normalise data/graph/graph.sqlite

# Score the 12 gold chunks on the GPU server: models x prompts, one comparison table. Needs Ollama.
gold12 *args:
    scripts/server_gold12.sh {{args}}

# TODO: scripts/eval/run.py does not exist yet. Pass `--short` for the CI subset.
eval *args:
    uv run python scripts/eval/run.py {{args}}

# Web UI + API on http://127.0.0.1:8000. Use `just run --fake` for canned demo data without Ollama.
# Full wiring to the real index/graph/MCP: see docs/api.md and docs/HANDOFF.md (open items).
# Unless --fake is among the args, scripts/preflight.py first checks Ollama and the models.
run *args:
    #!/usr/bin/env bash
    set -euo pipefail
    case " {{args}} " in
        *" --fake "*) ;;
        *) uv run python scripts/preflight.py ;;
    esac
    exec uv run python -m detective_board.api {{args}}

# Spike benchmarks (exist today). Heavy: needs Ollama; stop other model users first.
bench which="llm":
    uv run python scripts/spike/bench_{{which}}.py

# UI logic tests (node built-in runner; 2 live tests skip without DB_URL)
test-web:
    node --test tests/web_js/*.test.mjs
