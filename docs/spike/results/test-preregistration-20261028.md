# Preregistration of the test-split run (written BEFORE the run, 2026-10-28)

What is frozen: commit = HEAD of `main` at the time of the run (recorded in the result), agent defaults of `AgentConfig` as committed (extract_sentence_k 12,
extract_safety_chunks 4 x 3), generator qwen3:4b-instruct, graph = the server run of 2026-10-27 plus the 7 curated facts, sentence index of 11018
sentences, no `--set` overrides. The three prompts (`agent/extractive.py` SELECT_SYSTEM_PROMPT) are unchanged since the first measurement.

Command (clean tree, once): `uv run python eval/run_eval.py --split test` (configurations bare, vector, hybrid+graph; vector+rerank not run: no local reranker).

Primary metric (one, fixed): behaviour correct of hybrid+graph = answerable answered with key-fact coverage >= 0.5 (fixed coverage, `answer_coverage`),
out-of-corpus refused; share with its Wilson 95 % interval, n = 30. Secondary metrics, reported all: the same for bare and vector, the paired
McNemar comparisons, answer-sentence hit, citation correctness, refusal precision / recall, false refusal rate, recall@4, the contradiction detection
on the 20 test cases (findings on curated facts are NOT counted), median latency.

Expected before the run (so that nobody can say it was fitted afterwards): agent behaviour correct between 25 % and 45 %; bare below 20 %;
no significant difference agent vs vector; contradiction recall on automatic facts close to 0 (the extraction does not give the rules the facts).
Test cases c002 and c042 rest on curated facts and are reported separately.

Rules: the run is done once; a repeat only for a crash or a bug, said so in the report; the result is published whatever it is, including a drop
against dev; no tuning after seeing it; the dev numbers (tuned on the same 34 questions) are optimistic and are marked so.
