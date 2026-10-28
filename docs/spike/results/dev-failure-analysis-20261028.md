# Dev-split failure analysis of the agent (2026-10-28)

Source: `eval-2026-10-28-dev-ab945e8-78b3bbb3f2a6-145202-rescored.json` (34 dev questions, 27 answerable, 1 run), plus three live replays of
g023, g031 and g036 on the API (read-only; no code or config change). AI-written gold, so every number is against AI labels.

## Where the 27 answerable questions go (agent = hybrid+graph, extractive mode)

| class | n | questions | what it means |
|---|---|---|---|
| ok (key facts quoted) | 6 | g001 g002 g003 g020 g022 g025 | works |
| gold sentence quoted but the proxy scores it low | 4 | g018 g019 g032 g062 | answer is probably right; the key-fact proxy (coverage >= 0.5 of a long expected answer) is too strict. Not a failure of the agent |
| WRONG sentence although the gold chunk was retrieved (top 4) | 7 | g007 g010 g016 g028 g029 g038 g063 | selection problem: the model picks a neighbouring or plausible sentence. Largest class, the one the knobs below can move |
| false refusal although the gold chunk was retrieved | 5 | g023 g031 g036 g057 g061 | NOT the relevance gate: for g023, g031 and g036 the model was called (30-36 s, one 2 s from cache) and chose NONE ("no sentence answers the question", code no_evidence); candidate list has no sentence that answers it, or the model is too cautious. g057 and g061 are adversarial (false premise / prompt injection) and need a different behaviour than "refuse" |
| retrieval miss (gold chunk not in the top 4) | 5 | g009 g011 g034 g041 g044 | multi-hop and cross-story questions: a single-sentence extractive answer cannot answer them; by design |

## A fairer single number

"Behaviour correct OR the gold sentence is quoted" (any answerable question whose cited sentence overlaps the gold quote counts):
bare 4/34 = 12 %, vector-only 20/34 = 59 % [42, 74], agent 16/34 = 47 % [31, 63]; answerable only: vector 13/27, agent 10/27.
The agent is still behind vector-only on answer sentences (3 questions), within the noise of 34 questions (exact McNemar p = 0.25 on the original metric).

## Why the agent trails vector-only

1. Selection: the agent chooses among up to 40 candidate sentences (top 20 of the whole corpus plus 8 per source), vector-only works inside the top chunks. The gold sentence is among the top 20 candidates for 74 % (20/27) but is picked for 50 % (10/20 answered).
2. Extra citations: the agent adds sentences from other sources to the answer ("text evidence"); each is checked and counts, so "all citations correct" is 45 % against 74 % for vector-only. This is a display/metric choice, not a wrong selection.
3. NONE answers: 3 of the 5 false refusals are the model choosing NONE.

## What to try next (knobs only, no prompt change; each run: `python eval/run_eval.py --split dev --configs hybrid+graph`, about 20 minutes)

| id | change | hypothesis | decide by |
|---|---|---|---|
| E1 | `extract_sentence_k` 20 -> 12 | fewer distractors raise the selection hit | dev answerable ok count, no more false refusals |
| E2 | `extract_per_source` 8 -> 4 | the same | same |
| E3 | candidate order: best chunk's sentences first, then corpus-wide | model favours early candidates | same |
| E4 | show only the selected sentence as the citation (the other sources as links, not as cited quotes) | removes the citation penalty | citation-correct per answer |
| E5 | `min_support` / `min_score` | affects only refusals through the gate | refusal recall must not drop below 6/7 |

Rules: dev split only, one change at a time, adopt only with a clear gain (>= 3 more answerable questions right and no loss in refusal recall), re-record the five demo runs afterwards, run the test split ONCE on the final configuration. `agent/extractive.py` SELECT_SYSTEM_PROMPT must not change. The demo (tags rc1, rc2) runs the current defaults.
