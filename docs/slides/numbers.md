# Numbers used in the deck

Rule: a number is on a slide only if it is in this table with a source file and n. "Derived" means counted or subtracted by hand from rows of that file; the arithmetic is shown. `TBD` rows have no source yet and must be filled (or the slide must say "not yet measured") before the final deck. Source folders: `docs/spike/results/` (R), `docs/perf/`, `docs/STATUS.md`.

| # | Slide | Number | What it is | Source file | n / runs | Note |
|---|---|---|---|---|---|---|
| 1 | 1, notes | 300 tokens, cut by the limit | bare model answer to g001 | `docs/spike/results/answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl` (id g001: `tokens_generated` 300, `truncated_by_num_predict` true) | 1 question, 1 run | verbatim text on slide, labelled RECORDING |
| 2 | 4, notes | 9.3 s | g001 total time, extractive mode | `docs/spike/results/api12-20261027-extractive.md` | 1 of 12 questions, 1 run | not a rate; measure again in rehearsal |
| 3 | 6 | 0.17 and 0.25 | gate: share of question terms covered, threshold | `docs/spike/results/answers-20261023-v3-qwen3_4b-instruct.jsonl` (id g047, `gate.support`, `gate.min_support`; `llm_calls` 0) | 1 question | thresholds provisional |
| 4 | 6, notes | 0.01 s; 0.2 s | g047 refusal time (older run; 12-question run) | same jsonl `total_s` 0.0098; `api12-20261027-extractive.md` | 1 run each | slide says no LLM call |
| 5 | 7 | 6 of 10 | answerable questions with a quoted sentence, extractive | `docs/spike/results/api12-20261027-extractive.md` | 12 questions, 1 run | derived: answerable = 10 (expected answer or correct_premise: g001 g007 g028 g032 g016 g019 g022 g038 g057 g062); status answered for g001 g028 g032 g019 g022 g038 = 6. g028's "answer" is a rule sentence, not a quote. "Answered" is not "correct" |
| 6 | 7 | 2 of 2 | out-of-corpus questions refused (g047, g056) | same file | 12 questions, 1 run | |
| 7 | 7, B4, notes | 8.1-20.2 s | seconds per question that called the model, extractive | same file (min g019 8.1, max g038 20.2) | 12 questions, 1 run | gate refusals (0.2 s) excluded |
| 8 | 7 | 5 of 10 | answered and verified / answerable, qwen3:4b-instruct, retrieval-only | `docs/spike/results/answers-20261023-v3.md` | 12 questions, 1 run | AI-written gold |
| 9 | 7 | 8 of 12 | behaviour correct | same file | 12 questions, 1 run | |
| 10 | 7, 1 | 1 of 3 vs 2 of 3 | bare model vs agent behaved as required on out-of-corpus + adversarial | same file, line "On out-of-corpus + adversarial (3 questions)" | 3 questions | tiny n |
| 11 | 7, B3 | 70 of 86 = 81% | gold chunk within top 4; also 63/86 = 73% (top 3), 72/86 = 84% (top 5) | `docs/spike/results/evidence-20261023-093201.md` | 86 answerable questions | retrieval only, no LLM |
| 12 | B3 | 0.63 / 0.97 (hit@1 / hit@5); 0.60 / 0.91 | hybrid RRF k=30 w 0.5:1; hybrid k=10 w 1:1 | `docs/spike/results/arms-20261023-080849.md` | 35 questions | tuned on the same questions: optimistic |
| 13 | 8, B4 | about 21 tokens/s (21-22) | CPU prefill | `docs/perf/ttft-levers-2026-10-26.md` | 1 run per variant | |
| 14 | B4 | 42.7 s vs 52.7 s | 1080-token prompt with and without cached system prefix | same file | 1 run per variant | |
| 15 | 8 | 3195 MiB | peak RSS of qwen3:4b-instruct | `docs/spike/results/llm-20261022-171202.md` (3195.3) | 3 runs plus warm-up | |
| 16 | B4 | 45.7-140.8 s | generative mode, per question that called the model | `docs/spike/results/api12-20261027-generative.md` | 12 questions, 1 run | |
| 17 | B4 | 42.0 s first token; 59.5 s total | retrieval-only generative check | `docs/spike/results/answers-20261023-v3.md` | 12 questions, 1 run | |
| 18 | B1 | 107 events, 137 claims, 0 exact times, 0 days, 1 usable proposition, 19 pairs, 16 undecided | first real extraction run, wisteria-lodge, after repair | `docs/STATUS.md` (2026-10-27 morning) | 1 story, 1 run | |
| 19 | B1 | 7 / 1 and 15 / 11 | presence-2.1 facts / kept, qwen3:4b-instruct and qwen3:8b | `docs/spike/results/presence21-c001-20261027.md` | 3 chunks, 1 run | precision unmeasured |
| 20 | B2 | 0.557 / 0.200 / 0.136 (v2.1); 0.000 / 0.283 / 0.026 (v2.2); deny share 91% vs 12%; participants 0% vs 33% | strict F1 entities / claims / relations, qwen3:4b | `docs/spike/results/prompt-v2-2-20261026.md` | 12 gold chunks, 1 run | AI-labelled gold; v2.2 not adopted |
| 21 | 9 notes | i7-12700K, 96 GB, RTX 4070 12 GB | department server | `docs/STATUS.md` | - | hardware description, not a measurement |
| 22 | 9 | 4 genuine R1 and 3 R2 cases | corpus content | `docs/spike/REPORT.md` section 10 (risk 4) | whole corpus | **outside the allowed source folders**; counted by the spike, no file in `results/`. Remove from the slide if a reviewer insists on the folder rule |
| 23 | 10 | 596 chunks | corpus size | `docs/STATUS.md` ("596 chunks") | - | descriptive count |
| 24 | 2, 3 | 20 stories | corpus size | `README.md` | - | descriptive count, not a result |
| 25 | 5 notes | 1.1 s recorded; milliseconds of the tool call | R1 recording total; live MCP time | `web/replay/real-wisteria-r1-curated.json` meta `seconds`; live ms read from the screen | 1 recording | recording meta is not in the allowed folders; the live ms value is TBD (rehearsal log) |
| 26 | B5 | 25.3 s | Boscombe recording duration | `web/replay/real-boscombe-control.json` meta | 1 recording | operator information only |
| 27 | 7, 5 notes | 596 of 596 chunks, 20 of 20 stories, 2157 claims, 1698 events; 0 rule findings in 19 of 20 stories; 52.5% / 4.5% / 0.7% | full-corpus graph from the server run | `docs/spike/results/graph-sanity-20261028.md` (server report and normaliser log next to it) | 596 chunks, 1 run | extraction quality not scored beyond 12 gold chunks |
| 28 | 7 | 5 of 6, 30.3-43.2 s | dev questions answered with a quoted sentence on the full graph, laptop | `docs/perf/laptop-20261029.md` / `laptop-20261029-3x6.json` (earlier single run: `laptop-20261028.md`) | 6 questions, 1 run | not a clean window |
| 29 | 8 | 6289 MB; 98-100 C; median 28.4 s (18.6-44.1 s) | peak RSS of all llama-server processes; maximum package temperature | same file | 1 run | not final |
| 30 | 7 | 4/34 = 12%, 15/34 = 44%, 12/34 = 35%; McNemar p 0.001 (bare vs vector), 0.0215 (bare vs agent), 0.25 (vector vs agent, 3 vs 0) | behaviour correct (mechanical proxy), bare / vector / hybrid+graph | `docs/spike/results/eval-2026-10-28-dev-ab945e8-78b3bbb3f2a6-145202-rescored.md` (.json, .svg) | 34 dev questions, 1 run | rescored from the recorded answers with the fixed coverage; the first report (same name without `-rescored`) scored extractive answers 0 by a bug and must not be quoted; AI-written gold; test split not run |
| 30b | 7 | 14/34 = 41% [26, 58]; 13/22 = 59%; 7/7; 5/27; 9/22 | tuned agent (extract_sentence_k 12, safety chunks 4 x 3): behaviour correct; gold sentence quoted; out-of-corpus refused; false refusals; all citations correct | `docs/spike/results/eval-2026-10-28-dev-4bceaf8-dcf42c8a3eb8-162624.md` (.json, .svg); experiments: `docs/spike/results/dev-failure-analysis-20261028.md` | 34 dev questions, 1 run, hybrid+graph only | the settings were chosen on the same dev questions (E1 11, E2 11, E3 13, E5 13 of 27 answerable ok; baseline 10); optimistic; not significant (3 gained, 0 lost, p 0.25) |
| 33 | 7 | 3/30 = 10% [3, 26], 11/30 = 37% [22, 54], 13/30 = 43% [27, 61]; McNemar p 0.0215 (bare vs vector), 0.0063 (bare vs agent), 0.5 (vector vs agent, 2 vs 0); gold sentence 11/18 = 61% vs 7/18 = 39%; refusal recall 6/6; contradiction recall 0/12, false positives 0/8 | TEST split, run once, preregistered: bare / vector / hybrid+graph | `docs/spike/results/eval-2026-10-28-test-7b7b197-7857839ed9be-175321.md` (.json, .svg); `docs/spike/results/test-preregistration-20261028.md` | 30 test questions, 20 test cases, 1 run | mechanical proxy, AI-written gold; findings on curated facts not counted |
| 31 | 7 | 18/27 = 67% vs 21/27 = 78% (recall@4); 4/7, 7/7, 6/7; 20/27, 8/27, 7/27; sentence hit 13/19 = 68% vs 10/20 = 50% | recall@4; refusal recall; false refusal rate (bare / vector / hybrid+graph) | same files | 27 answerable, 7 out-of-corpus | these numbers are identical in both reports |
| 32 | 7, 10 | 0/14 recall, 0/9 false positives | contradiction detection by the rules on the automatic graph | same file | 23 dev cases | findings not matched to the case's own claims (optimistic by design), still 0 |

## Open markers (TBD)

| Marker | Where | Needed from |
|---|---|---|
| `TBD` one-command rebuild; clean-window laptop table with 3 repeats and the 8 GB profile | slide 8 | clean-window laptop run |
| Gold-review date and reviewer | slide 9 | gold-review report |
| Human re-check of curated facts | slide 9 | team |
| MCP tool time in ms for step 2 | demo-script rehearsal log | rehearsal 1-3 |
| Per-result hardware, written organizer approval | `docs/DISCLOSURE.md` | team lead |
