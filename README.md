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
just run           # API + UI; preflight checks Ollama and models first (`just run --fake` needs neither)
just test-web      # UI logic tests (node)
just bench llm    # spike benchmark; needs a running Ollama and pulled models; also: embed, retrieval, rss
```

Spike scripts can also be run directly, for example `uv run python scripts/spike/bench_llm.py`. Stop other model users first, since measurements depend on free RAM and CPU.

## How to reproduce the numbers

The eval runner is `eval/run_eval.py` (issue #6). It runs four configurations with the same generator, `qwen3:4b-instruct` (think off):

| configuration | what it is |
|---|---|
| `bare` | the question to the model, no retrieval, no sources |
| `vector` | bge-m3 vector search only, top 4 chunks into the agent's answer path |
| `vector+rerank` | reported as `not run`: the repo has no local reranker (`retrieval/rerank.py` is a stub) |
| `hybrid+graph` | the real agent: hybrid retrieval, sentence index, graph, rules, extractive answers |

```bash
just eval --short            # 8 dev questions, FakeLLM, fixture index, no network (the CI job eval-short)
just eval --split dev        # real stack: Ollama with qwen3:4b-instruct and bge-m3, data/index/db.sqlite,
                             # data/index/sentences.sqlite and data/graph/graph.sqlite
just eval --split test       # the frozen test split: once per frozen configuration, refused with uncommitted changes
```

Output: `docs/spike/results/eval-<date>-<split>.md` (tables), `.json` (one row per question and configuration, the git SHA, whether the tree was clean, a hash of the configuration) and `.svg` (behaviour correct per configuration with intervals); short runs go to `eval/runs/` (git-ignored).

Protocol: tune thresholds on the dev split only (`eval/golden/split.json`, checked by `scripts/eval/split_check.py`); run the test split once per frozen configuration and quote its SHA and config hash with every number. Heavy runs go to the GPU server; on the target laptop only latency is meaningful.

What the numbers are: mechanical proxies, no judge model. Behaviour correct: an answerable question answered with key-fact coverage >= 0.5, an out-of-corpus one refused. Citation correct: the quote is verbatim in the cited chunk and that chunk is a gold chunk. Answer-sentence hit: a cited quote overlaps a gold quote. Refusal precision, recall and false refusals; chunk recall@1/4/6; contradiction detection (rules only) on `eval/golden/contradictions.jsonl`. Every share has a Wilson 95 % interval and its n; configurations are compared pairwise with an exact McNemar test. The gold sets are AI-written until the human review of issue #9 is done, and every table says so.

## Docs

`docs/PRD.md` (goals, non-goals), `docs/acceptance/acceptance.md`, `docs/backlog.md`, `docs/test-plan.md`, `docs/design/` (board and demo script), `docs/demo/jury-faq.md`, `docs/STATUS.md`.

Disclosure and licences: [docs/DISCLOSURE.md](docs/DISCLOSURE.md) (what was precomputed where, models, gold-set provenance, corpus licence) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
