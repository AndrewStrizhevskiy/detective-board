# Phase 0 spike report

Date: 2026-10-23. Status: complete except the answer-model check (section 9, PENDING). Every number comes from a file in `docs/spike/results/` or from a scorer run on those files. Anything derived shows its arithmetic.

## 1. Goal and method

Choose models and storage for an offline, CPU-only Holmes corpus (20 stories, 596 chunks) and find which parts of the design are at risk.

| Question | Experiment | Script | Result files |
|---|---|---|---|
| LLM speed | 1 warmup + 3 runs per prompt, temperature 0, seed 42, num_ctx 4096, RSS sampled every 0.5 s | `bench_llm.py` | `llm-20261022-17*` |
| Embedding model | speed on 50 chunks/pass; story-level hit (15 EN + 5 RU); chunk-level hit/MRR (35 questions) | `bench_embed.py`, `bench_retrieval.py` | `embed-*`, `retrieval-*` |
| BM25 / vector / hybrid | real `retrieval` module, 22 configs, 35 questions | `bench_arms.py` | `arms-20261023-080849.md` |
| Extraction | 12 labelled chunks, constrained JSON-schema decoding, 6 models | `run_extraction.py`, `score_extraction.py`, `overlap_metric.py` | `extract-*.jsonl` |
| Answer model | real Agent, retrieval-only path, 12 golden questions | `eval/run_answer_check.py` | PENDING |

## 2. Environment

- i7-8665U (4 cores), 15 GiB RAM, CPU only, Ollama 0.35.0. RSS is that of the `llama-server` child runner.
- Thermal (`max_temp_c` at run start/end): 4B models 74-88 C. qwen2.5:7b and qwen3:8b went from 84 C to 96 C. Sustained 7-8B load throttles, so their section 3 tok/s are probably flattering for long jobs.
- Model digests were not recorded, only tags.

## 3. LLM speed (clean runs)

Prompt: 300-word chunk (about 400 tokens), up to 200 generated tokens, mean of 3 runs, think=false for qwen3.

| Model | gen tok/s | TTFT s | prompt tok/s | cold load s | peak RSS MiB | short_qa tok/s / TTFT |
|---|---|---|---|---|---|---|
| gemma3:4b | 7.73 | 15.30 | 26.5 | 15.62 | 4127 | 8.25 / 1.91 |
| phi4-mini | 7.73 | 17.09 | 22.7 | 18.41 | 3336 | 8.53 / 1.47 |
| qwen3:4b | 7.07 | 17.19 | 23.4 | 9.34 | 3526 | 8.12 / 1.76 |
| qwen3:4b-instruct | 7.04 | 19.46 | 22.2 | 8.09 | 3195 | 8.18 / 1.71 |
| qwen2.5:7b | 4.92 | 27.00 | 15.5 | 14.61 | 5029 | 5.17 / 2.82 |
| qwen3:8b | 4.34 | 29.49 | 13.8 | 15.37 | 6033 | 4.65 / 3.82 |

Invalid runs (`_invalid_run1`, `_invalid_run2`), excluded everywhere:
- Run 1: the sampler watched the parent `ollama` PID and missed the `llama-server` child that holds the weights.
- Run 2: the previous model stayed resident. For example gemma3:4b showed 9955 MiB and MemAvail 4967 MiB, against 4127 MiB and 12220 MiB in the clean run.

## 4. Embeddings

Speed (`embed-*`):

| Model | dim | chunks/s | peak RSS MiB | 596 chunks (derived) |
|---|---|---|---|---|
| bge-m3 | 1024 | 0.46 | 2076 | 21.6 min |
| arctic | 1024 | 0.49 | 780 | 20.3 min |
| nomic | 768 | 1.29-1.31 | 457 | 7.7 min |
| minilm | 384 | 9.36 | 172 | 1.1 min |

Story-level smoke test (n=15 EN, n=5 RU; one question is 7 or 20 points):

| Model | EN hit@5 | EN hit@1 | RU hit@5 | RU hit@1 |
|---|---|---|---|---|
| bge-m3 | 1.00 | 0.93 | 1.00 | 0.60 |
| nomic, with prefixes | 1.00 | 0.80 | 0.20 | 0.00 |
| nomic, no prefixes | 0.93 | 0.87 | 0.00 | 0.00 |
| arctic | 1.00 | 0.93 | 0.20 | 0.20 |
| minilm | 0.93 | 0.67 | 0.00 | 0.00 |

Chunk-level (`retrieval-*`, n=35):

| Model | hit@1 | hit@5 | hit@10 | MRR | recall@10 | RU hit@5 | hard hit@5 |
|---|---|---|---|---|---|---|---|
| bge-m3 | 0.57 | 0.89 | 0.94 | 0.70 | 0.91 | 1.00 | 0.83 |
| nomic | 0.43 | 0.69 | 0.74 | 0.53 | 0.73 | 0.00 | 0.75 |
| arctic | 0.26 | 0.63 | 0.69 | 0.41 | 0.64 | 0.00 | 0.75 |
| minilm | 0.26 | 0.46 | 0.51 | 0.35 | 0.51 | 0.00 | 0.67 |

Only bge-m3 answers Russian questions, and it also leads on the English ones. Prefixes in the chunk-level runs: nomic `search_query: ` / `search_document: `, arctic query prefix `Represent this sentence for searching relevant passages: `, bge-m3 and minilm none.

## 5. Retrieval arms (bge-m3, 35 questions)

| Arm | hit@1 | hit@5 | hit@10 | MRR | recall@10 |
|---|---|---|---|---|---|
| BM25 OR | 0.46 | 0.69 | 0.80 | 0.55 | 0.77 |
| BM25 AND | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Vector | 0.57 | 0.89 | 0.94 | 0.70 | 0.91 |
| Hybrid k=10, w=1:1 | 0.60 | 0.91 | 0.97 | 0.73 | 0.96 |
| Hybrid k=30, w bm25:vec 0.5:1 (best) | 0.63 | 0.97 | 0.97 | 0.75 | 0.96 |

- BM25 returns an empty list for 5 of 5 Russian questions, so hybrid equals vector-only there.
- Stop-word stripping did not help (hit@1 0.57 against 0.63).
- **Caveat:** k and the weights were tuned on the same 35 questions they are scored on, so 0.97 is optimistic. The gain over vector-only is +2 questions at hit@1 and +3 at hit@5, a direction and not a proven lift. No confidence interval; the question set was partly built by the project itself.
- One miss remains at k=5 (hard-04, rank 65). A reranker has room only at hit@1.

## 6. Extraction pilot

Settings: constrained decoding, temperature 0, seed 42, num_ctx 4096, num_predict 1536, 12 chunks.
- **Strict scorer** (`score_extraction.py`) matches entities by name or alias, and claims and relations by speaker or subject plus quote token-F1 >= 0.5. It does not score events.
- **Overlap scorer** (`overlap_metric.py`) counts a hit when quotes overlap in the chunk text, ignoring speaker and wording.
- Gold size: 105 entities, 56 claims, 43 relations.

| Model | valid JSON | quotes verbatim | strict F1 ent / claim / rel | overlap F1 ent / claim / rel / event | s per chunk | gen tokens per chunk |
|---|---|---|---|---|---|---|
| qwen3:4b | 12/12 | 0.934 | 0.55 / 0.31 / 0.18 | 0.51 / 0.48 / 0.45 / 0.46 | 179.7 | 964 |
| qwen3:4b-instruct | 11/12 | 0.908 | 0.58 / 0.28 / 0.24 | 0.58 / 0.50 / 0.35 / 0.44 | 235.3 | 1092 |
| qwen3:8b | 12/12 | 0.896 | 0.68 / 0.26 / 0.12 | 0.56 / 0.43 / 0.33 / 0.49 | 332.0 | 1058 |
| qwen2.5:7b | 12/12 | 0.841 | 0.60 / 0.30 / 0.10 | 0.57 / 0.40 / 0.33 / 0.43 | 283.4 | 1107 |
| gemma3:4b | 12/12 | 0.794 | 0.61 / 0.16 / 0.20 | 0.63 / 0.30 / 0.32 / 0.40 | 185.0 | 1097 |
| phi4-mini | 12/12 | 0.871 | 0.63 / 0.10 / 0.09 | 0.63 / 0.33 / 0.37 / 0.39 | 174.4 | 1034 |

- qwen3:4b-instruct had one truncated output (`red-headed-league-0003`, hit the token cap).
- 7-21% of produced quotes are not substrings of the chunk, so items must be re-anchored or dropped before they enter the graph.
- Effective speed was 3.2-5.9 tok/s, below the section 3 numbers. Thermal throttling and parallel agent work are suspected but not measured; wall times after about 22:00 on 2026-10-22 were taken while agents ran short tests.

Caveats:
1. Only 12 chunks, so differences among the top four on claims (0.26-0.31) are noise.
2. The gold labels were generated automatically and not reviewed by a human.
3. Gold is not exhaustive, so precision is understated and recall is the more reliable side.
4. The overlap metric is lenient (any overlap counts) and inflated for claims and relations. It measures "found the right passage".
5. Events are scored only by the lenient metric.

## 7. Cost projection (derived: s per chunk x 596)

| Model | total seconds | hours |
|---|---|---|
| phi4-mini | 103,954 | 28.9 |
| qwen3:4b | 107,089 | 29.7 |
| gemma3:4b | 110,284 | 30.6 |
| qwen3:4b-instruct | 140,227 | 39.0 |
| qwen2.5:7b | 168,924 | 46.9 |
| qwen3:8b | 197,890 | 55.0 |

- The bge-m3 index takes 596 / 0.46 = about 22 min, once (already built from cache).
- A full-corpus run with qwen3:4b is about 30 h of exclusive CPU against a freeze in 5 days. It collides with every other benchmark.
- One story is about 30 chunks, so about 1.5 h with qwen3:4b.
- Time scales roughly with generated tokens, so a smaller schema should cut it. The size of that cut is unmeasured.

## 8. Recommendations

| Decision | Choice | Confidence |
|---|---|---|
| Embeddings | bge-m3 | High |
| Retrieval | SQLite FTS5 + sqlite-vec, hybrid RRF k=30, w 0.5:1, BM25 in OR mode | Medium (tuned on the evaluation questions) |
| Extraction | qwen3:4b, think off | Medium-low (12 chunks, automatically labelled gold) |
| Answer model | qwen3:4b-instruct (section 9) | Medium-low (n=12) |
| Reranker | not needed for hit@5 | Medium |

Latency: qwen3:4b gives 17.2 s + 150/7.07 = about 38 s for a 150-token answer (the length is an assumption).

## 9. Answer-model check (2026-10-23, real Agent, retrieval-only path)

Files: `docs/spike/results/answers-20261023-v3.md` and `answers-20261023-v3-<model>.jsonl`. 12 fixed golden questions, one run each, temperature 0, seed 42, agent defaults (top_k 4, rank_full: top-1 chunk whole + 3 windows of 60 words, 1200-token budget, hybrid RRF k=30 w 0.5:1). Graph and MCP tools off.

| Model | behaviour correct | answered+verified / answerable | coverage (crude) | cites gold chunk | TTFT s | total s per question | prompt tokens |
|---|---|---|---|---|---|---|---|
| qwen3:4b-instruct | 8/12 | 5/10 | 0.33 | 5/10 | 42.0 | 59.5 | 1110 |
| gemma3:4b | 6/12 | 4/10 | 0.11 | 2/10 | 43.5 | 82.6 | 1220 |
| qwen3:8b | 9/12 | 5/10 | 0.19 | 5/10 | 101.1 | 141.5 | 1166 |

- **Decision: qwen3:4b-instruct for answers.** qwen3:8b is at most one question better (noise at n=12) and 2.4x slower to first token. gemma3:4b is worse.
- qwen3:4b with think=false still writes its reasoning into the answer (fails the self-check), so it is unusable for chat answers; it remains the extraction model (constrained JSON output is unaffected).
- Bare-LLM baseline (qwen3:4b-instruct, no retrieval): it confidently denies true facts (for g001: Roylott "was not killed by a snake") and invents context; behaved as required on 1/3 out-of-corpus/adversarial questions, the agent on 2/3.
- Failure causes found and fixed on the way (all visible in git history): window selection without IDF weights; a strict system prompt without an example made the 4B model refuse even with the answer in the prompt; the sentence splitter cut "Dr."; the eval script did not pass the IDF file. The remaining misses are mostly retrieval: the gold chunk is in the top-4 for about 81% of answerable questions (`evidence-20261023-093201.md`: the gold evidence is inside the prompt for 66-69%).
- The Russian question is refused by the relevance gate before any LLM call (the lexical support check fails across languages); Russian remains optional.
- Caveats: n=12, one run per model, crude coverage proxy, no human judging, gold generated automatically, thresholds provisional.
- Latency at the chosen setting: about 42 s to first token and 60 s total on average on this CPU. The demo must show trace events and retrieved quotes while the model prefills.

## 10. Risks

1. Claims and relations are weak on every model (strict F1 0.09-0.31), and the rules R1-R3 consume exactly these.
2. R1 and R3 need time and claim-property normalisation, and free-text times are the weak link. This was not measured in the spike.
3. All gold sets were generated automatically and not reviewed by a human.
4. The corpus has only 4 real R1 and 3 R2 cases, and R3 dominates.
5. Samples are small everywhere (35 retrieval questions, 12 extraction chunks, 3 speed runs).
6. About 30 h of extraction against a 5-day freeze.
7. sqlite-vec is pre-v1 (pinned 0.1.9). The `docs/security.md` findings do not block the model choices.

## 11. Needs the customer

1. Human spot-check of the gold sets (all claims and relations of 4 extraction chunks, and 10 golden questions).
2. Extraction scope: full corpus or demo stories only (orchestrator default: priority stories first, see STATUS.md).
3. Acceptance that the answer model stays open until the check runs, and that the extraction model rests on thin evidence.

## Addendum 2026-10-27

Appended after the first runs of the real stack; sections 1-11 above are unchanged and still describe the 2026-10-23 state (retrieval-only path, graph and MCP off). Every number here is from a named file; n is small everywhere, so read all of it as pilot.

### A1. The two real-API runs of the 12 control questions

Same 12 questions as section 9, now through `POST /api/ask` on the target laptop with the real index (596 chunks), a graph of 8 stories (231 chunks) plus curated demo facts, live bge-m3 embeddings and qwen3:4b-instruct. One run each, temperature 0, seed 42. Files: `results/api12-20261027-generative.md` (before) and `results/api12-20261027-extractive.md` (after); decision record: ADR-0009.

| | Generative (decline-retry, closest-passages fallback) | Extractive (model chooses sentences) |
|---|---|---|
| time per question that called the model | 45.7-140.8 s | 8.1-20.2 s |
| g001 | partial (closest passages; 7.3 s only through Ollama prompt cache) | answered, 9.3 s, verbatim swamp-adder sentence |
| g047 / g056 / g057 | refused / partial / partial | refused / refused / refused |
| g007, g016 | partial | refused (model chose NONE) |
| g062 (Russian) | refused by the gate | refused by the gate |
| g028, g022 | rule-first template although they are text questions (regression, fixed afterwards) | g028: rule line plus text evidence; g022 answered from text |

Caveats (from the files): n=12, one run; "answered" means a quoted sentence, not a correct one; no human has judged the answers; the 4B model is wording-sensitive (one clause of the selection prompt flipped g001 to NONE), so the prompt wording is frozen; the generative table was measured on the same day before the extractive mode existed, so the two runs differ in the code, not only the mode.

### A2. What the real extraction showed (symbolic readiness)

- Raw qwen3:4b output with `extract-2.1` over 64 cached Wisteria/Boscombe chunks: participants empty in all events (178/178 in the brief of 2026-10-27; `docs/symbolic-layer.md` 11.2 counts 177 events and 226 claims), `polarity=deny` in 222 of 226 claims (98%), time and place copied from the chunk start. R1/R3 found nothing (133 `DENIAL_NOT_MODELLED`, 0 dated events).
- After the deterministic repair (STATUS 2026-10-26; produced with `scripts/eval/repair_eval.py`, not re-run for this addendum): participants non-empty in 122 of 177 events, deny share 16%, copied time/place demoted to low inherited context.
- First real run, wisteria-lodge, repaired: 107 events, 137 claims, 0 exact clock times, 0 story days, 1 usable presence proposition; R1 examined 19 pairs and could not decide 16. So R1/R3 still find nothing automatically on real data: the text rarely gives exact times and days.
- Prompt v2.2 (12 gold chunks, `results/prompt-v2-2-20261026.md`): participants non-empty 33% vs 0%, deny share 12% vs 91%, but strict F1 entities 0.000 vs 0.557 and relations 0.026 vs 0.136; claims 0.283 vs 0.200. Not adopted (ADR-0012). The repair reproduces the polarity gain on v2.1 output.

### A3. Targeted presence pass

Three c001 chunks only. presence-1 (qwen3:4b-instruct 16 facts, qwen3:8b 12 facts): strict grounding kept 0, lenient kept 2, because the models write pronouns as the person. presence-2.1 (graph candidate names as a JSON-schema enum plus carry-over from earlier chunks): qwen3:4b-instruct 7 facts, 1 kept (one chunk truncated); qwen3:8b 15 facts, 11 kept, the key fact right and several wrong persons or places. The presence-2.1 counts were reported by the team lead and are not in a committed result file. Precision is unmeasured. The demo therefore uses five curated facts (`data/curated/presence_demo.jsonl`, ADR-0011), marked as such everywhere.

### A4. Time to first token

Prefill is about 21 tokens/s; threads, batch size and num_ctx change nothing beyond noise; only the system-prompt prefix cache helps (42.7 s against 52.7 s for the 1080-token g001 prompt; `docs/perf/ttft-levers-2026-10-26.md`, one run per variant). The extractive prompt is about a third of the generative one, which is where the 8-20 s per question comes from.

### A5. Server and what remains unmeasured

Department server: i7-12700K, 96 GB, RTX 4070 12 GB, fully ours until 2026-11-01; slots Tue 27 Oct from 14:30 and Wed 28 Oct 12:00-18:00; organizers approved precomputing elsewhere; freeze Wed 18:00. The laptop cache of 231 chunks (8 stories, `data/extraction/laptop-cache-qwen3_4b-extract-2.1.sqlite`) seeds the server run.

Unmeasured at the time of writing: extraction on all 596 chunks (counts of events with exact times and days); precision and recall of automatic presence facts; qwen3:8b against qwen3:4b on the gold12 with v2.1; contradiction precision/recall on a real graph; human-judged correctness of extractive answers; the extractive mode on more than 12 questions or more than one run; the human re-check of the curated facts; GPU versus CPU differences in cached extraction outputs.
