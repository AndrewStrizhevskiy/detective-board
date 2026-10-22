# Backlog
Format: `- [ ] ID | owner | task | acceptance | priority | day`
Priority: P0 = never cut, P1 = needed for plan, P2 = cut first (see order). Days are 2026-10-23..29; show 2026-10-30.

## Cut order (first to cut)
1. UI animations (T-33)
2. Second own MCP server (T-22)
3. Temporal graph subtleties beyond rules R1-R3 (T-14)
Never cut: working demo, citations, honest refusals, quality measurements.

## Tasks
- [ ] T-36 | graph-engineer | Rules module `src/detective_board/symbolic/` in pure Python (no LLM, no I/O, no network): R1 one person in two places in overlapping intervals; R2 before/after transitive, cycle detection; R3 witness claim vs established fact. Every result is a `derived` finding with an explanation object (rule id, fact/edge ids, source quotes) and `conditional` when an input is a low-confidence `extracted` fact. Design: docs/adr/0004-symbolic-layer.md, docs/symbolic-layer.md | rules importable and callable on an in-memory graph; AC-21, AC-22, AC-24 (module level) | P0 | 10-23 (first task of Phase 1)
- [ ] T-37 | test-automation-engineer | Deterministic unit tests for R1-R3 on hand-built mini graphs with known answers and boundary cases (touching intervals, equal endpoints, unknown times, 2- and 3-cycles, self-order, empty graph, claim vs unknown fact), run twice with identical output; no Ollama, no network | AC-23; 100% green in `just test` | P0 | 10-23
- [ ] T-01 | data-engineer | Chunk and index corpus (596 chunks), store with story/chunk ids | AC-01 prerequisite; reindex reproducible by one command | P0 | 10-23
- [ ] T-02 | devops-engineer | One-command run and offline setup via justfile | AC-13 | P0 | 10-23
- [ ] T-03 | retrieval-engineer | Baseline RAG: embeddings retrieval plus answer with quotes | AC-01, AC-02 | P0 | 10-23
- [ ] T-04 | eval-engineer | Eval set and runner skeleton (reuse eval/spike_questions.jsonl, add gold) | AC-14 runs on baseline | P0 | 10-23
- [ ] T-05 | tech-lead | ADRs: models per role, graph store, trace event schema | docs/adr populated | P1 | 10-23
- [ ] T-06 | retrieval-engineer | Hybrid retrieval (lexical plus embeddings, fusion) | recall@k beats baseline on eval (target TBD) | P0 | 10-24
- [ ] T-07 | nlp-extraction-engineer | Offline entity/claim extraction to graph (persons, places, items, events, claims) | spot-check sample with quotes; run fits CPU budget | P0 | 10-24
- [ ] T-08 | graph-engineer | Graph store and query API | AC-11 data side | P0 | 10-24
- [ ] T-09 | backend-engineer | Agent API with streamed trace events | AC-10, AC-12 backend | P0 | 10-24
- [ ] T-10 | graph-engineer | GraphRAG retrieval (graph expansion on top of hybrid) | A/B row in eval | P0 | 10-25
- [ ] T-11 | agent-engineer | Router (retrieval/graph/tools/refusal) | AC-09 | P0 | 10-25
- [ ] T-12 | agent-engineer | Self-check: quote verification and refusal gate | AC-02, AC-03, AC-04 | P0 | 10-25
- [ ] T-13 | mcp-engineer | MCP server 1: corpus search, graph query; `check_alibi`, `find_overlaps` and contradiction tools are thin wrappers over the rules module (T-36), no rule logic in the server, explanation object in outputs (docs/mcp-contracts.md) | AC-07, AC-25 | P0 | 10-25
- [ ] T-14 | graph-engineer | Temporal subtleties beyond R1-R3: durations, relative times ("an hour later"), fuzzy intervals. The core rules are T-36 and are not cut | AC-07 on harder cases | P2 | 10-27
- [ ] T-15 | agent-engineer | Contradiction detection: the agent calls the rules (R1, R3) via the rules module or MCP and phrases the explanation; the LLM does not decide whether a contradiction exists. Confidence is carried from the extracted inputs | AC-05, AC-06, AC-24 | P0 | 10-26
- [ ] T-16 | agent-engineer | Multi-tool orchestration | AC-08 | P1 | 10-26
- [ ] T-17 | frontend-engineer | Board UI: question box, answer panel, trace panel | AC-10 | P0 | 10-25
- [ ] T-18 | frontend-engineer | Live graph view with click-to-quote | AC-11 | P0 | 10-26
- [ ] T-19 | ux-designer | Board layout and demo flow polish | readable on projector | P1 | 10-26
- [ ] T-20 | security-reviewer | Injection test chunk and MCP path sandbox review | AC-16, AC-17 | P0 | 10-26
- [ ] T-21 | mcp-engineer | Path sandbox for file-access tool | AC-17 | P0 | 10-26
- [ ] T-22 | mcp-engineer | Second own MCP server | one extra tool visible in trace | P2 | 10-27
- [ ] T-23 | eval-engineer | A/B run: baseline vs hybrid vs GraphRAG vs agent; fix PRD target numbers | AC-14, AC-15 | P0 | 10-27
- [ ] T-24 | performance-engineer | Latency pass: prompt sizes, caching, model choice per role | AC-12; numbers recorded | P1 | 10-27
- [ ] T-25 | qa-lead | Run acceptance suite, log defects | AC list status in STATUS.md | P0 | 10-27
- [ ] T-26 | test-automation-engineer | Automated tests for quote validity, refusal, sandbox, injection | AC-02, AC-16, AC-17 | P1 | 10-27
- [ ] T-27 | demo-director | 7-minute script, scripted questions, cache for them | AC-18, AC-19 | P0 | 10-27
- [ ] T-28 | tech-lead | FREEZE: feature freeze, only fixes | tag, branch protection by convention | P0 | 10-28
- [ ] T-29 | qa-lead | Full regression on frozen build | AC-01..19 verdicts | P0 | 10-28
- [ ] T-30 | eval-engineer | Final eval run and honest report | AC-14, AC-15 | P0 | 10-28
- [ ] T-31 | tech-writer | README and run instructions, final PRD metrics | AC-13 from clean checkout | P1 | 10-28
- [ ] T-32 | demo-director | Rehearsals on target laptop (timed) | AC-18 | P0 | 10-28, 10-29
- [ ] T-33 | frontend-engineer | UI animations | none; cosmetic | P2 | 10-27
- [ ] T-34 | demo-director | Fallback plan (recorded run, cached answers) | demo survives model hang | P1 | 10-29
- [ ] T-38 | frontend-engineer | UI provenance badges `extracted` / `derived` / `conditional` and explanation panel (rule, facts, edges, quotes) | AC-20, AC-21, AC-22; docs/design/board-design.md 1.6 | P0 | 10-26
- [ ] T-39 | eval-engineer | Separate eval for contradiction detection by the rules (precision/recall on gold cases, incl. cases lost to extraction errors), reported apart from answer quality | AC-14, AC-15, AC-24; own table in the report | P0 | 10-27
- [ ] T-35 | product-owner | Daily STATUS, scope control, final go/no-go | STATUS.md updated daily | P0 | 10-23..29

## Requests from ux-designer / demo-director (2026-10-22)
- [ ] R-01 | backend/agent | Refusal path without an LLM call (templated from the `refusal` event, with `missing[]` and nearest rejected chunks) | refusal visible within seconds; demo step 4 live | P1
- [ ] R-02 | backend | `cached: true` on `run.start`; stored-run replay from `trace_log` keyed by question+index hash+model+prompt version, gaps capped at 2 s | REPLAY badge; AC-19 | P0
- [ ] R-03 | frontend | Operator key `c` (serve cached run), REPLAY/LIVE badge, waiting-for-first-token counter with prefill estimate, candidate-evidence cards before the answer | docs/design/board-design.md sections 1, 7 | P0
- [ ] R-04 | frontend | Run `python3 docs/design/contrast_check.py` in `just lint`/CI | token edit cannot regress contrast | P2
- [ ] R-05 | agent-engineer | Bare-model command (same model id, no retrieval, temperature 0, seed 42) and a `verify-quotes` check usable on any text | demo step 5 | P1
- [ ] R-06 | agent-engineer | Confidence band thresholds from eval calibration (provisional in board-design 1.4) | documented | P2

## Requests from graph-engineer (2026-10-22)
- [ ] R-07 | nlp-extraction-engineer | Schema changes wanted in `extract/schema.py` (not made by graph-engineer): (a) structured claim proposition (`PresenceProp`/`OrderProp` per docs/symbolic-layer.md 1.2) with confidence; today `GraphStore.set_claim_prop` takes it from a normaliser; (b) `Event.in_speech: bool` (event reported inside a quotation), now approximated by claim-span containment; (c) `Event.transit: bool` (presence vs motion), now a motion-verb list in symbolic; (d) optional `Entity.unnamed` flag; (e) optional model confidence per item, otherwise confidence stays derived (anchor ambiguity, implicit/unresolved references, time guesses) | R3/R1 stop depending on curation overlays and heuristics | P1
- [ ] R-08 | data-engineer / graph-engineer | Story day (`story_day`) for events is not derivable from `time_text`; needs a day-resolution step ("last Monday", "the next morning" with a reference event) writing `GraphStore.set_event_day`. Until then R1/R3 return `unknown` unless `SqliteFactSource(assume_day=...)` is used (always low confidence). Also `same_occurrence` event dedup across chunks (symbolic `EventRec.occurrence_id`) is not produced | R1/R3 produce definite verdicts on real extractions | P1

## Decisions and follow-ups (night of 2026-10-22, orchestrator)
- D-01 Raw corpus passages shown in the UI carry the label `source_text` (verbatim quote of the corpus), next to `extracted`, `derived`, `conditional`. Add to AC-20 wording and the UI badge set.
- R-09 | agent-engineer | Self-check quote matching must normalise whitespace/curly quotes (reuse extract/ground normaliser) | P1
- R-10 | backend-engineer | Sync ToolClient adapter over the async MCP session; SSE endpoint streaming Agent.ask events (DOC_TYPE mapping in agent/events.py) | P0
- R-11 | graph-engineer | Store schema-v2 fields (claim about_*/polarity, event in_speech/transit, entity unnamed); day-resolution + claim-prop normaliser owned by extract pipeline, consumed by graph/symbolic | P0
- R-12 | agent-engineer | Entity linking for MCP args (story/person ids) instead of top-hit heuristic | P1
- R-13 | eval-engineer | Tune min_score (0.018) and min_support (0.25) on the golden set | P1
