# Handoff (2026-10-23, 13:00) - read this first

> Current plan and schedule: [docs/ROADMAP.md](ROADMAP.md) (2026-10-25).

Work by the orchestrator stopped here on the customer's request so the team can continue on stronger
machines. Everything below is committed on `main`. Nothing is running in the background.

## 0. Curated demo facts (2026-10-27, branch `feat/curated-demo-facts`, not pushed)

The automatic presence pass does not give the rules the Garcia facts of the Wisteria case (c001 needs
coreference). The demo cases therefore use human-checked ("curated") facts in
`data/curated/presence_demo.jsonl`, loaded into the graph with `python -m detective_board.extract.curated
--graph-db data/graph/graph.sqlite` (after the graph build and `just normalise`; idempotent; they survive
generic and presence re-ingests). They are labelled `curated` on the nodes, in the Explanation summaries
and in the rule-first answer, and the finding stays `conditional`. The automatic pipeline and its
numbers are untouched and reported separately. R3 positives were NOT added: no case of the contradiction
set is an explicit person-place-time conflict with an established narrator fact. Details, the limits of
the c042 control and how to add a case: `docs/symbolic-layer.md` 11.4; stage wording: `docs/DISCLOSURE.md`
and `docs/design/demo-script.md` step 2. The facts still need a human re-check.

## 0b. Sentence index (2026-10-27, branch `feat/sentence-index`, not pushed)

`data/index/sentences.sqlite` (`just sentences`; docs/data-schema.md 2b) is a sentence-level hybrid index; with it the extractive mode offers the top 12 sentences of the whole corpus plus the best 2 of each of the top 2 chunks (docs/api.md "Sentence index"). Without the file nothing changes (trace note in `enriched_query.strategy`). Candidate recall without an LLM: `eval/sentence_recall.py`, results in docs/spike/results/sentence-recall-*.md. Whether the model then picks the right sentence is NOT measured yet: run `eval/run_answer_check.py` on the real model before making it the demo default.

## 1. What the project is

Detective Board: a local, offline, CPU-only neuro-symbolic investigator over 20 Sherlock Holmes stories.
The LLM (<= 8B) extracts facts probabilistically, a graph stores them, deterministic rules (R1-R3) derive
checkable conclusions with quotes, and every answer cites verbatim text. Competition demo: 2026-10-30,
7-minute talk, on a ThinkPad X1 Carbon 7th gen (i7-8665U, 15 GiB, no GPU). Feature freeze 2026-10-28.
See `README.md`, `docs/PRD.md`, `docs/architecture/c4.md`.

## 2. State of the code (all tests green: `uv run pytest -q -m "not live"` = 562 passed; `just test-web`
42 passed + 2 skipped; ruff, format and pyright clean)

| Area | Where | State |
|---|---|---|
| Corpus, chunks with source anchors | `data/clean`, `data/chunks.jsonl`, `scripts/corpus` | done, 20 stories / 596 chunks |
| Retrieval (SQLite FTS5 + sqlite-vec, hybrid RRF) | `src/detective_board/retrieval` | done, tested |
| Index builder | `python -m detective_board.index.build` (`just index`) | done; reuses cached bge-m3 vectors if present |
| Extraction pipeline (JSON repair, quote grounding, cache, schema v2) | `src/detective_board/extract` | done; real runs only on the 12 spike chunks and ~30 pipeline chunks |
| Graph store (SQLite) + FactSource | `src/detective_board/graph` | done, tested with hand-built extractions; NOT yet filled from real extraction (wave 1 stopped) |
| Symbolic rules R1-R3 + explanations | `src/detective_board/symbolic` | done, 70 deterministic tests; real-data behaviour untested |
| MCP server `timeline-alibi` + client | `src/detective_board/mcp` | done, stdio integration test; serves one story from a FactBase JSON |
| Agent (router, relevance gate, cited answers, self-check, trace events) | `src/detective_board/agent` | done on fake LLM and a 12-question live check; graph/MCP route NOT live-tested |
| API (Starlette + SSE) and UI | `src/detective_board/api`, `web/` | done and browser-checked in `--fake` mode only |
| Eval | `eval/`, `scripts/spike`, `scripts/eval` | golden sets + spike scorers exist; the 4-configuration A/B runner `eval/run_eval.py` does NOT exist |

## 3. Decisions and the numbers behind them

Full report: `docs/spike/REPORT.md`. ADRs: `docs/adr/` (0001-0008). Short version:

- Embeddings: **bge-m3** (chunk-level hit@5 0.89 vs 0.46-0.69 for others; only one that handles Russian).
- Retrieval: hybrid RRF k=30, weights bm25:vec 0.5:1, BM25 OR mode (hit@5 0.97 on 35 questions, tuned on the
  same questions, so optimistic). The gold chunk is in the top 4 for about 81% of answerable questions.
- Answers: **qwen3:4b-instruct** (`docs/spike/results/answers-20261023-v3.md`, n=12). qwen3:8b is 2.4x slower
  to first token for at most one more correct question. `qwen3:4b` writes its reasoning into chat answers even
  with think off, so do not use it for answers. A system prompt WITH a format example is required; the strict
  prompt without example made the 4B model refuse.
- Extraction: **qwen3:4b, think off, constrained JSON**, prompt `prompts/extract/extract_v2_1.txt`
  (`docs/spike/results/ab-prompt-v2_1.md`: 25% faster than v2.0). About 190-250 s per chunk on the laptop, so
  the full corpus is 24-30 h of exclusive CPU: THIS IS THE JOB FOR STRONG MACHINES.
- Context for answers: top 4 sources, top-1 chunk whole, others 60-word windows chosen with IDF-weighted
  sentence scoring, 1200-token budget. Prefill runs at only 11-23 tokens/s on the laptop (about 40 s to first
  token); that is why the context is small.
- Graph storage: plain SQLite (no Ladybug, no networkx). Rules run on an in-memory FactBase (ADR-0004).

## 4. What to do next (priority order)

1. **Run the extraction on a strong machine** (Package A in `docs/team/ASSIGNMENTS.md`). Same Ollama model tags
   (`docs/team/models.md`), same prompt (now the default), temperature 0, seed 42:
   ```bash
   uv sync && uv run python scripts/extract_shards.py plan 4
   scripts/extract_shard.sh <k> 4 qwen3:4b            # each person runs one shard
   uv run python scripts/merge_extract_cache.py merge data/cache/extract-cache.sqlite \
       data/cache/extract-cache-qwen3_4b-shard*.sqlite --model qwen3:4b
   just graph qwen3:4b 20      # all cache hits: builds data/graph/graph.sqlite, then normalises (`just normalise`)
   ```
   A partial cache (26 chunks of boscombe-valley-mystery, v2.1) is in
   `data/extraction/extract-cache-qwen3_4b-extract-2.1-partial.sqlite` (force-added; `*.sqlite` is git-ignored).
   Verify determinism against it with `merge_extract_cache.py verify ... -n 3` before trusting a new machine.
   Ship the finished `extract-cache.sqlite` and `graph.sqlite` back (release asset or LFS; do not commit
   large binaries to git history).
2. **Score extraction quality of v2.1/schema v2** on the 12 gold chunks: `just gold12` (models x prompts, one
   table; `scripts/server_gold12.sh`) or `uv run python scripts/spike/score_pipeline.py OUT.jsonl`. Try prompt/schema variants to raise claims
   and relations (F1 only 0.2-0.5).
3. **Wire the real stack end to end** (see `docs/api.md`, `build_app(config)`): real index + graph + MCP
   server on the real graph; the router has no graph step for contradiction questions yet (UI works around it);
   claim-property and day normalisation (R-07/R-08/R-11 in `docs/backlog.md`) are needed or R1/R3 stay
   `unknown` on real data. Measure the contradiction set `eval/golden/contradictions.jsonl` separately.
   **Presence pass (branch `feat/presence-pass`, written, NOT measured).** A second, targeted extraction
   (`python -m detective_board.extract.presence`, prompt `presence_v1.txt`) asks only "person X at place P
   at time T" (narrator, witness speech, denials) with at most 6 short facts per chunk, grounds every field
   against its own quote, ingests events/claims (`GraphStore.ingest_presence`) and gives same-label days a
   LOW heuristic story day. Run it after the graph exists with `scripts/server_presence.sh` (qwen3:8b and
   qwen3:4b-instruct, then `scripts/spike/presence_eval.py`); details and limits in
   `docs/symbolic-layer.md` 11.3. The tests use canned model output: they show the plumbing, not extraction
   quality, and Wisteria Lodge (c001) is only reachable with `--lenient` (context fields, LOW).
   **Presence verifier (branch `feat/presence-verifier`, NOT measured):** optional `--verify` (one enum-answer check per kept fact) and `--samples N` (majority vote) for the presence pass, off by default, recommended server command in `docs/team/SERVER_RUNBOOK.md` 5b; per-stage precision/recall in `presence_eval.py`; see `docs/symbolic-layer.md` 11.3.
4. **Build `eval/run_eval.py`** (Package C): bare LLM / vector / vector+rerank / hybrid+graph; heavy runs on
   the strong machine, a short CI mode. Tune the provisional thresholds (min_score 0.018, min_support 0.25,
   min_claim_overlap 0.3; R-13).
5. **Human review of the AI-written gold sets** (`eval/golden/README.md`, `eval/extraction_gold/README.md`).
6. UI items in `docs/backlog.md` (R-15/R-16), packaging and clean-machine test, slides and rehearsals
   (Package D, `docs/design/demo-script.md`). Measurements of speed/RAM only on the target laptop.

## 5. Known issues and traps

- Ollama 0.35 runs the model as a `llama-server` child process: RSS must be read there. Unload other models
  before measuring (`keep_alive: 0`). Sustained 7-8B load reaches 96 C and throttles.
- Do not use `pkill -f` / `pgrep -f` with a pattern that also appears in your own shell command line.
- `uv run` here uses CPython 3.14; the project requires >= 3.12 and CI should pin 3.12.
- Gold sets and labels were written by a Claude agent: precision numbers are underestimates, recall is more
  trustworthy; every metric file states its caveats.
- The Russian question is refused by the relevance gate before the LLM (cross-language support check); optional.
- Only 4 genuine R1 (person in two places) and 3 R2 (order cycle) cases exist in the corpus; R3 dominates.
- `docs/security.md` lists open security items (extraction-time injection, non-loopback bind, checksums,
  pip-audit/gitleaks, off-the-shelf MCP server criteria).
- Invalid or aborted benchmark outputs are kept under `docs/spike/results/_invalid_run*` and `_aborted` for
  the record; never cite them.

## 6. Repository map

`src/detective_board/{retrieval,index,extract,graph,symbolic,mcp,agent,api}`, `web/`, `prompts/extract/`,
`eval/` (golden sets, spike questions, answer check, evidence study), `scripts/` (corpus, spike benchmarks,
shard/merge tools, priority runner), `docs/` (PRD, architecture, ADRs, symbolic-layer, api, security,
test-plan, design, demo, team, spike), `.claude/agents/` (the 20 agent definitions used by the orchestrator),
`CONTRIBUTING.md`.
