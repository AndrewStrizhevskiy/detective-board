# Roadmap to release (written 2026-10-25 evening)

Show: Fri 2026-10-30 (talk about 7 minutes + questions). Feature freeze: **Wed 2026-10-28 12:00**.
State on 2026-10-25: all modules exist and are tested on fake and hand-built data (474 Python tests, 50 UI logic
tests, CI green); nothing has run end to end on a real extracted graph. Read `docs/HANDOFF.md` for the facts.

## 1. Critical path (any delay moves the demo)

```
A  extract on strong machines  ->  B  merge cache, normalise, build graph.sqlite  ->
C  wire real stack (paths, MCP over the graph, router)  ->  D  measure + choose demo questions  ->
E  freeze, package offline, rehearse
```
Everything else runs in parallel tracks (section 4) and must not wait for A.

## 2. Schedule

| When | Critical path | Parallel tracks | Gate at end of block |
|---|---|---|---|
| **Sun 25 eve** | Ask the organizers whether precomputing the index/graph on other hardware is allowed (and plan to say it on stage anyway). Start extraction shards tonight on the strong machines (prompt v2.1, qwen3:4b, think off, temp 0, seed 42). In parallel score v2.1 on the 12 gold chunks (a GPU makes a rerun cheap). Tiny PR: unify default paths (`data/index/db.sqlite`, `data/graph/graph.sqlite`) in `api/config.py`, `index/build.py`, `scripts/run_extraction_priority.sh`, `extract/normalise.py`, docs. | Assign owners (section 3). Open issues for R-19 (P0), R-02/R-03, eval runner, packaging. | **G0**: owners assigned, shards running, path PR merged |
| **Mon 26** | Merge shard caches (`merge_extract_cache.py`), build the graph (`run_extraction_priority.sh qwen3:4b 20` = all cache hits), run `python -m detective_board.extract.normalise`. Sanity: counts per story, share of events with time, share of claims with a proposition, dropped quotes. If quality is bad, adjust the prompt on the GPU machine and rerun (hours, not days). | R-19: stdio MCP server over the graph (`SqliteFactSource`), agent uses real MCP by default, in-process only as fallback. UI demo modes R-02/R-03 (recorded runs, RECORDING badge, key `c`, refusal without LLM R-01). `eval/run_eval.py` (4 configurations, metrics, table+chart, short CI mode). Packaging scripts (offline archive, clean-machine checklist). Security leftovers + CI (Python 3.12, pip-audit, gitleaks). Human review of the AI-written gold sets. | **G1** (Mon night): `graph.sqlite` exists, sanity numbers recorded in `docs/spike/` |
| **Tue 27** | Integration day on the **target laptop**: `just index` (or copy the vectors), `just run` on the real index/graph/Ollama with qwen3:4b-instruct. Fix integration bugs. Run `eval/golden/contradictions.jsonl` against the real graph (rule-only, no LLM) and the golden answers on the real stack (GPU machine for the long eval, laptop for latency). Tune thresholds (min_score, min_support, min_claim_overlap, R-13). Pick the demo questions that really work (`docs/design/demo-script.md`), including one where the bare LLM really errs. | Merge all feature PRs by **18:00**; independent human review for each. Update ADR-0005 (DOM+SVG board instead of Cytoscape, R-17), README, architecture. Slides skeleton ("where the agent guesses and where it proves"). | **G2** (Tue 18:00): the real stack answers the demo questions; metrics tables exist; CI green on `main` |
| **Wed 28** | **Freeze at 12:00 (bugfix only).** Performance on the laptop in a clean window (nothing else running): TTFT, tokens/s, RSS, 16 GB and 8 GB profiles, saved to `docs/perf/`. Final eval table and chart. | Record the backup screen recording and replay files for every demo step. Build the offline archive (models, wheels, index, graph). Finalize README, metric descriptions, ADR index, licences (dependencies, Gutenberg corpus). Jury FAQ updated (BUILT / DESIGNED / TBD tags re-checked). | **G3**: frozen tag `rc1`, numbers final |
| **Thu 29** | Clean-machine install from the archive without network, twice (two different laptops). Fix only showstoppers. | Rehearsals 1 and 2 with a timer; fix script, wording, fallbacks. Final slides. USB copy of the archive + video. | **G4**: offline install passes twice; rehearsal under 7 minutes |
| **Fri 30** | Morning: rehearsal 3, smoke test of the exact laptop setup, power and thermal check (no other apps, charger plugged). | Final checklist, tag `v1.0`. | **G5** go/no-go, then the show |

## 3. Owners (adjust to the people available)

| Track | Owner |
|---|---|
| A, B extraction and graph build | strong-machine teammate(s) (Package A) |
| C real wiring: paths, R-19 MCP over the graph, router follow-ups R-22 | LitrumCoder |
| UI demo modes (R-01/02/03), remaining R-15, record/replay files | paramonovdan |
| Eval runner, thresholds, gold-set human review | teammate (Package C) + a human reviewer |
| Packaging, offline archive, clean-machine test, CI/security leftovers | teammate (Package D) |
| Integration day, laptop measurements, rehearsals, final go/no-go | project lead (you), with the tooling in `scripts/` |

## 4. Parallel tracks that never wait for the graph

UI modes and polish; `eval/run_eval.py`; packaging; docs and slides; CI/security; human review of gold sets;
demo script rewrite (step 2 is now Wisteria Lodge R1, not McCarthy vs Crowder: gold c042 is a consistent control).

## 5. Release criteria ("done")

1. `just run` starts the UI on the real index and graph, offline, from a clean machine, on one command.
2. The demo questions run live (or as clearly labelled recordings) with verbatim citations, honest refusals,
   at least one derived finding with its Explanation, and a real MCP tool call (stdio, not in-process).
3. Measured on the target laptop and written down: TTFT, tokens/s, RSS, 16/8 GB profiles.
4. Quality table (bare LLM / vector / vector+rerank / hybrid+graph) with caveats; contradiction detection
   precision/recall and false-positive rate on controls reported separately from answer quality.
5. CI green on `main`; coverage of the core at least 80%; security items closed or explicitly accepted.
6. Docs consistent with reality; every non-built item still marked planned; licences recorded.
7. Offline archive tested twice; backup recording for every demo step; three timed rehearsals.

## 6. Risks and fallbacks (decide early, do not improvise on Fri)

| Risk | Early signal | Fallback |
|---|---|---|
| Extraction quality too low for rules | G1 sanity numbers (few events with time, few claim props) | Demo built on the stories where it works (Wisteria Lodge R1, Boscombe R3); label the rest as text retrieval; do not hide it |
| Strong machines unavailable or not allowed | no reply from organizers / shards not started by Mon morning | Laptop-only: extract priority stories overnight (about 275 chunks, about 14 h) |
| Latency on stage (about 40 s to first token) | Tuesday measurement | Stream trace and evidence during prefill; recorded runs clearly labelled; cached answers for the demo set |
| Real MCP over the graph not ready | R-19 not merged Tue 12:00 | Single-story facts file for the stdio server for the demo stories (works today), in-process only for others, say so |
| Bare LLM does not err on the chosen question | Tuesday trial | Pick another question that really fails; never stage an error |
| Thermal throttling / RAM pressure | temperatures above 90 C in tests | Charger, cooling pad, nothing else running; keep qwen3:4b-instruct only |
| Scope creep after freeze | new feature PRs on Wed | Reject; only bugfixes with tests |

Cut order if time runs out: (1) UI animations, (2) second own MCP server (evidence-notes: not built, drop),
(3) temporal subtleties of the graph, (4) extraction coverage (priority stories only), (5) reranker.
Never cut: a working demo, citations, honest refusals, quality measurements.
