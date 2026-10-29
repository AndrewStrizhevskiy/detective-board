# Presence pass on the GPU server: first full run (2026-10-29)

Run for issue #20 (who-was-where-when). Raw files are not committed (cache, graphs, jsonl); the numbers below are
copied from `eval-s3-verify.json` and the `*.report.json` files of the run.

## Setup

- Server `iu5-b7-aih-0` (RTX 4070), project copy from main `e775761`, graph rebuilt from the 596-entry extraction
  cache (all cache hits, no model calls), then the 8 curated facts loaded.
- Command: `scripts/server_presence.sh --verify --samples 3` (default prompt `presence-2.1`, verifier
  `presence-verify-1.0`, candidates from the graph). Demo stories only: wisteria-lodge, boscombe-valley-mystery,
  silver-blaze, thor-bridge, abbey-grange; 159 chunks per model.
- Models: `qwen3:8b` (10.3 s per chunk, 1985 s total) and `qwen3:4b-instruct` (7.1 s per chunk, 1431 s total).
- Robustness: valid JSON 100 % (8b) and 99.4 % (4b-instruct); 0 failed chunks; 1 truncated answer (4b-instruct).

## Funnel

| Stage | qwen3:8b | qwen3:4b-instruct |
|---|---|---|
| Facts from the model | 537 | 587 |
| Quote and field grounding | 101 | 122 |
| After majority vote (2 of 3 samples) | 103 | 103 |
| After the verifier | **16** | **7** |
| Chunks with at least one kept fact | 14 of 159 | 6 of 159 |

Dropped, by reason (8b / 4b-instruct): `TIME_NOT_IN_QUOTE` 223 / 144, `TIME_NOT_TEMPORAL` 115 / 150,
`VERIFY_REJECTED` 87 / 96, `VOTE_BELOW_MAJORITY` 31 / 60, `PLACE_UNKNOWN` 10 / 85, `PERSON_UNKNOWN` 9 / 42,
`POLARITY_UNCLEAR` 25 / 19, `duplicate` 36 / 5, `PERSON_NOT_A_NAME` 11 / 9, `quote_not_grounded` 7 / 5,
`quote_too_long` 0 / 6.
Verifier rejections by detail: 8b `person_no` 61, `partly` 25, `no` 1; 4b-instruct `person_no` 94, `partly` 1, `no` 1.

Kept facts: 9 / 6 come from speech, 0 / 0 are denials, **0 / 0 carry a story day** (`kept_with_day_text`), 12 / 4 carry
context fields only (LOW).

## Score against the gold set

`gold.jsonl` has only **4 strict gold facts** (20 in the broad set), so these figures are not stable.

| Model, stage | Precision | Recall (full) | F1 | Judged predictions |
|---|---|---|---|---|
| 8b, grounded / voted | 0.0 / 0.0 | 0.0 | 0.0 | 5 / 5 |
| 8b, verified | 0.0 | 0.0 | 0.0 | 0 |
| 4b-instruct, grounded | 0.333 | 0.75 | 0.462 | 9 |
| 4b-instruct, voted | 0.429 | 0.75 | 0.545 | 7 |
| 4b-instruct, verified | 1.0 | 0.75 | 0.857 | 3 |

4b-instruct's precision 1.0 rests on 3 judged predictions; for 8b none of the 16 kept facts matched the gold set, so no
precision is defined. Neither number supports a claim about quality.

## What it shows

1. The main loss is time. About 340 (8b) and 290 (4b-instruct) facts fail on time: the model writes a time that is
   not in the quote, or one that is not a time.
2. The verifier rejects mostly person mismatches. A hand check of 12 random rejected 8b facts (a small, subjective
   sample, not a measurement) found the rejections mostly justified: the quotes are future instructions ("Leave
   Paddington by the 11:15"), plans, hypotheses or someone else's time. The extraction proposes facts from sentences
   that are not presence statements; the verifier is not obviously too strict.
3. No kept fact has a story day, so rule R1 still cannot compare kept facts across events. The rules stay starved
   (`docs/spike/results/graph-sanity-20261028.md`: 0 findings in 19 of 20 stories on the automatic graph).
4. Some kept facts are doubtful: person "Randall gang", places "the hollow" and "the room above". Some are useful
   and agree with the curated ones, for example Garcia at Wisteria Lodge "about eleven" (8b, wisteria-lodge-0006).

## Consequence for the demo

Automatic presence facts are not enough to replace the curated ones. The demo keeps the 8 curated facts with their
`curated` label; the statement in `docs/DISCLOSURE.md` stays valid.

## Not done

- The 16 + 7 kept facts were not checked by a human, and the gold set is too small to give intervals.
- `--lenient`, `--literal` and a 100-fact human-checked set (issue #20, step 1) were not run or built.
- The rule recall on `eval/golden/contradictions.jsonl` with these facts was not measured.
- The presence graphs (`data/graph/presence-*.sqlite`) stay on the server, not committed.
