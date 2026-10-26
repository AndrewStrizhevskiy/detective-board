# Detective Board

A local, CPU-only **neuro-symbolic system** that investigates 20 Sherlock Holmes stories. The LLM extracts knowledge from text (probabilistic). A graph stores it with verbatim source quotes. Deterministic rules draw verifiable inferences (alibi conflicts, event-order contradictions, witness claims against facts), each with an explanation: which facts and edges, with which quotes. Answers cite the text, and the agent refuses when the corpus does not support an answer.

Status: Phase 0 done; Phase 1 code exists and is tested on fake and small real data (retrieval, extraction pipeline, graph, rules, MCP, agent, API, UI). Full-corpus extraction and real-data wiring are open; see "What exists" below and docs/HANDOFF.md.

> **Handoff:** read [docs/HANDOFF.md](docs/HANDOFF.md) for the current state and next steps.

## Provenance labels

| Label | Made by | Property |
|---|---|---|
| `extracted` | the model | probabilistic, carries a confidence |
| `derived` | a rule | deterministic, carries an explanation |
| `conditional` | a rule | derived from a doubtful `extracted` fact |

Rules (minimum): R1 one person cannot be in two places in overlapping time intervals; R2 event order is transitive and has no cycle; R3 a witness claim incompatible with an established fact is a contradiction. Limitation: extraction errors pass into the symbolic layer, so a derived finding follows from the stated facts, not necessarily from the story.

## Architecture (target design)

```mermaid
flowchart LR
  corpus["20 stories (data/clean)"] --> ext["LLM extraction (Ollama, offline pipeline)"]
  ext -->|"extracted facts + quotes"| graph[("Knowledge graph")]
  corpus --> idx["Hybrid index (BM25 + embeddings)"]
  graph --> rules["Rules R1-R3 (pure Python)"]
  rules -->|"derived findings + explanations"| agent["Investigator agent: router, self-check"]
  idx --> agent
  graph --> agent
  agent <--> mcp["MCP server timeline-alibi (wraps the same rules)"]
  mcp --> rules
  agent --> ui["Board UI: graph, trace, answer, explanation panel"]
```

Details: `docs/architecture/c4.md`, `docs/adr/` (0004: symbolic layer), `docs/symbolic-layer.md`, `docs/mcp-contracts.md`, `docs/data-schema.md`.

## What exists today (2026-10-22)

- Built: corpus fetch/ingest scripts (`scripts/corpus/`), 20 cleaned stories and 596 chunks (`data/`), chunk-level extraction schema v1 with a grounding rule (`src/detective_board/extract/schema.py`), a 12-chunk extraction gold set (agent-labelled, not human-reviewed), spike benchmarks for LLM speed, embeddings and retrieval (`scripts/spike/`, results in `docs/spike/results/`), unit tests for ingest, extraction scoring and retrieval bench helpers (`tests/`), docs and ADRs.
- Planned, not built: rules module `src/detective_board/symbolic/`, provenance labels, graph layer, retrieval layer, agent, MCP servers, UI, eval runner. The `just index`, `just eval` and `just run` recipes are placeholders until those land.

## Run what exists

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just). The first setup needs network.

```bash
just setup        # create the environment (uv sync --group dev)
just test         # fast deterministic tests, no Ollama
just lint         # ruff
just index         # data/index/db.sqlite (retrieval index)
just graph         # data/graph/graph.sqlite from the extraction cache, then normalise
just run           # API + UI; reads exactly those two files (`just run --fake` needs none)
just bench llm    # spike benchmark; needs a running Ollama and pulled models; also: embed, retrieval, rss
```

Spike scripts can also be run directly, for example `uv run python scripts/spike/bench_llm.py`. Stop other model users first, since measurements depend on free RAM and CPU.

## Docs

`docs/PRD.md` (goals, non-goals), `docs/acceptance/acceptance.md`, `docs/backlog.md`, `docs/test-plan.md`, `docs/design/` (board and demo script), `docs/demo/jury-faq.md`, `docs/STATUS.md`.

Disclosure and licences: [docs/DISCLOSURE.md](docs/DISCLOSURE.md) (what was precomputed where, models, gold-set provenance, corpus licence) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
