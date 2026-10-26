# Contributing

Four teammates, each with Claude Code, work in parallel on separate branches. Everything must be
merged into `main` by **2026-10-27 18:00**; feature freeze is **2026-10-28**. Work packages:
`docs/team/ASSIGNMENTS.md`. Read `docs/PRD.md`, `docs/adr/`, `docs/backlog.md` first.

## Setup

```bash
git clone <origin> detective-board && cd detective-board
uv sync --group dev            # Python 3.12, pinned deps; `just setup` does the same
# Ollama (https://ollama.com), then the models listed in docs/team/models.md:
ollama pull bge-m3 && ollama pull qwen3:4b && ollama pull qwen3:4b-instruct \
  && ollama pull gemma3:4b && ollama pull qwen3:8b
ollama list                    # IDs must match docs/team/models.md
uv run pytest -m "not live"    # sanity check, no Ollama needed
```

Optional: `uvx pre-commit install`. UI e2e only: `uv sync --group e2e && uv run playwright install chromium`.
Raw corpus and indexes are not in git: rebuild them with the scripts in `scripts/corpus/` and
`just index` (writes `data/index/db.sqlite`; the graph is `data/graph/graph.sqlite` via `just graph`), or ask for a data archive.

## Branches

`feat/<area>-<short>`, `fix/<area>-<short>`, `exp/<area>-<short>` (experiments, may never merge).
Areas: `extract`, `retrieval`, `graph`, `agent`, `api`, `web`, `eval`, `ops`, `docs`.
Example: `feat/eval-run-eval`, `exp/extract-prompt-v3`. Branch from fresh `main`, keep branches
short-lived, rebase on `main` before opening the PR. Never push to `main` directly.

## Commits

Conventional Commits: `feat(extract): ...`, `fix(web): ...`, `docs: ...`, `test: ...`,
`chore: ...`. Imperative, English, one logical change per commit. **No `Co-Authored-By` and no
"Generated with ..." lines**, in commits or PR text.

## Pull requests (into `main`)

1. Description: what and why, linked backlog ID (T-xx / R-xx), how to reproduce.
2. Tests added or updated; `just lint test typecheck` green locally (CI runs the same).
3. Independent review: the `code-reviewer` agent (checklist in `.claude/agents/code-reviewer.md`:
   correctness, types, tests, error handling, interface adherence, docs, scope; verdict
   APPROVE / CHANGES) **and** one human teammate. Paste the agent verdict in the PR.
4. Squash or rebase merge; the author fixes review items, the reviewer re-checks.
5. Measurements of speed or RAM are valid **only on the target laptop (ThinkPad X1, 7th gen)**.
   Numbers from any other machine must be labelled as such in the PR ("measured on <GPU/CPU>,
   not the target laptop, not valid for AC-12") and never go into STATUS/PRD as final.
   Quality metrics (accuracy, claims counts, recall) are hardware-independent only if model
   tag, prompt, temperature 0 and seed are identical; say so.

## Zones of ownership

Each Claude Code agent role in `.claude/agents/*.md` has a **Zone** line (for example
frontend-engineer: `src/detective_board/web/`). Edit only files in your package's zones (listed
per package in `docs/team/ASSIGNMENTS.md`). Need a change elsewhere: add a request line to
`docs/backlog.md` (format `R-nn | owner | what | priority`) and tell the owner; do not edit it.
Cross-zone changes found in review are rejected.

## Do not commit

`data/raw/`, `data/cache/`, `data/index/`, `data/graph/`, `data/embeddings/`, any `*.sqlite`,
`*.faiss`, `*.npy`, model files or archives, large files (> 1 MB without a good reason; use
a release asset or shared drive), `.env*`, keys, tokens, `*.session`, screen recordings.
`.gitignore` covers most of this; check `git status` before every commit.
Small result summaries (`docs/spike/results/*.md|json`) are fine.

## Tests

```bash
uv run pytest -m "not live"          # fast, deterministic, no Ollama (also: just test)
just test-web                        # UI logic tests (node --test tests/web_js)
just lint                            # ruff check + format --check
just typecheck                       # pyright
uv run pytest -m live                # needs Ollama + models; never in CI
uv run pytest -m e2e                 # Playwright, needs the e2e group
```

Heavy things (model runs, benchmarks) are run only when you have the machine to yourself; say
in the PR what you ran and on what hardware.

## Running extraction in parallel

`scripts/extract_shard.sh <shard-id> <n-shards> [model]`, then
`scripts/merge_extract_cache.py merge ...`. Details in `docs/team/ASSIGNMENTS.md` (Package A)
and `docs/team/README.md`.
