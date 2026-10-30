# Suspect board before the reveal: frozen protocol (written before the test run, 2026-10-29)

Cases: `eval/suspects/cases.jsonl` (16 stories, AI-written, not yet human-checked). Split: `eval/suspects/split.json`
(alphabetical, even = dev, odd = test), fixed before any run. The test split is run **once** with the settings below.

Model: `qwen3:8b`, Ollama on the GPU server, temperature 0.3 and 3 votes for evidence cards, long-context call at
temperature 0, `num_ctx` 20480. Candidates from the graph built on 2026-10-29 (`data/graph/graph.sqlite`).

Methods reported on test, all with frozen parameters: matrix (lam 1.0, kind bonus 0.5, min support 2, margin 1.0),
long-context ranking (abstain when the model says confidence low), ensemble `agree` (answer only when the matrix and the
long-context model name the same top candidate), ensemble `either`, the bare model, and the baselines (random in
expectation, most mentioned, most accused by suspicion words). Each with names open and with names masked.

Parameter search on dev (grid over lam, min support, margin, abstain-low, kind bonus; score = correct - 2 x wrong):
no setting beat the defaults by more than one case on 8 dev stories, so the defaults are kept. Dev numbers
(8 cases, 5 where the culprit is named before the cut): matrix open 3 correct / 4 wrong, long-context open 2 / 1 with
5 abstentions, ensemble agree open 1 / 0 with 7 abstentions, most mentioned 3 / 5, bare model 2 / 6.

Primary claim to test: the system does not accuse the innocent (wrong answers among answered cases). Secondary: the
culprit first, the culprit in the top 3. Baseline numbers for all 16 cases were looked at before this note (they
involve no tuning); no decision rests on them.
