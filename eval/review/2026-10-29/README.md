# Human review of the gold sets: kit of 2026-10-29 (issue #9)

The golden questions, the contradiction cases and the extraction labels were written by an AI
agent. Nobody has reviewed them yet (`docs/DISCLOSURE.md`, table "Human review status"). This
folder is what two people need to do the review of issue #9. The issue estimates about 10
person-hours; with the passages already cut out it should be less (UNVERIFIED until the first
reviewer writes down their times).

| Sheet | Items | Rows in `verdicts.csv` |
|---|---|---|
| `golden.md` | 20 golden questions: the 13 the issue names, g027 (see below), and 6 more from the test split | 20 |
| `contradictions.md` | 16 cases: the 10 the issue names, and 6 more; together all 6 `confidence=low` and all 10 `confidence=medium` cases, no `high` | 16 |
| `extraction.md` | every claim and relation of 4 chunks (testimony and times, what the rules read); their entities and events are **not** in this review | 32 |

Each golden question and contradiction case shows its text, the expected answer or finding, the
author's note, and each quote **inside its passage** from `data/clean/` (the quote in bold). An
extraction chunk shows its own text with the claims and relations listed under it. A script has already checked that
every quote is verbatim, and where: **0 failures** on 2026-10-29. That only proves the words
exist. Whether they **support** the answer is what the review decides.

Built by `python3 scripts/eval/review_kit.py --date 2026-10-29`. The selection is seeded and
fixed, so re-running gives the same items. A re-run never overwrites a `verdicts.csv` that
already has verdicts in it. The sheets are a snapshot of the files on that date. Building the
kit moves nothing between dev and test (but see step 4).

## How to review (about 5 minutes per item)

1. Take your letter. `assignee` in `verdicts.csv` splits the rows into A and B; each chunk stays
   with one person. Agree among yourselves who is A.
2. Read the item in its sheet, and the wider story text if the passage is not enough
   (`data/clean/<story>.txt`).
3. Fill your rows in `verdicts.csv`:

| column | what to write |
|---|---|
| `reviewer` | your GitHub login |
| `date` | the day of the review, `YYYY-MM-DD` |
| `verdict` | `ok` (correct as it is) · `fixed` (you corrected the text of the item in the file: describe it in `fix`) · `drop` (wrong, cannot be fixed: say why in `fix`; the eval-engineer removes it) · `unsure` (needs a second opinion, **or** the item needs another category or kind: write the proposal in `fix`) |
| `fix` | what was wrong and what you changed; empty for `ok` |
| `time_min` | minutes spent on the item |

4. A fix goes into the item itself, in `eval/golden/*.jsonl` or `eval/extraction_gold/*.json`:
   the answer, the quote or the note (but keep its `confidence=` tag: the kit's selection of the
   extra contradiction cases is ranked by it). **Do not change `id`, `category` (golden) or `kind`
   (contradictions), and do not delete an item.** The dev/test split is computed from category
   and kind (`split.json`), so any of these moves other items between dev and test. For example,
   relabelling c042 moves c033 into test and c019 out of it. Write such a change as `unsure` or
   `drop` with the proposal in `fix`; the eval-engineer decides. Afterwards run
   `python3 scripts/eval/validate_golden.py`, `python3 scripts/eval/validate_contradictions.py`
   and `python3 scripts/eval/split_check.py`. All three must say OK.
5. Run `python3 scripts/eval/apply_review.py eval/review/2026-10-29/verdicts.csv`. It checks the
   CSV and writes `reviewed_by` / `reviewed_on` into every golden question and contradiction case
   with verdict `ok` or `fixed`. An extraction chunk is marked only when all its rows are `ok` or
   `fixed`, with `reviewed_scope: ["claims", "relations"]` (its entities and events stay
   unreviewed). Its `--status` prints the line for the table in `docs/DISCLOSURE.md` and both
   READMEs.

## g027 against c042: a decision for the reviewers

The issue asks to resolve this disagreement. Both items read the same two statements of
*The Boscombe Valley Mystery* (the inquest evidence, as Holmes reports it):

- Crowder (the game-keeper): "To the best of his belief, the father was actually in sight at the
  time, and the son was following him."
- James McCarthy: "but he is mistaken in thinking that I was following my father"

c042 adds a third quote from Crowder, which its "both agree" rests on: "going the same way with a
gun under his arm".

**g027** (golden, testimony-contradiction, test split) asks *how the accounts differ*. Expected:
Crowder believed the son was following; James says he was not.

**c042** (contradiction case, consistent_control, test split; the "Boscombe control" of the demo)
asks *whether that is a contradiction in what happened*. Expected: no. Both agree James went the
same way with a gun; they differ only about intent, and Crowder states it as his belief.

AI reading, for the reviewers to accept or reject: the two items do not contradict each other.
They ask different questions. The accounts do differ (g027), but about a belief and its denial,
not about an observed fact (c042). The outcomes:

- **Both stand** (the AI reading): mark both `ok`, and add a cross-reference to each note ("see
  c042: the accounts differ on intent, not on observed facts", and the reverse). Editing notes is
  allowed.
- **c042 is not a control**: if a belief against a denial *is* a conflict of accounts for this
  project, c042 is mislabelled. `R3_claim_vs_fact` fits poorly, since both statements are claims and
  neither is a narrator's fact. Mark it `unsure` with the proposal (relabel or drop). Either one moves
  items between dev and test (step 4), and the demo's control case and its slide change too, so the
  eval-engineer and the demo-director decide.
- **g027 is not a contradiction question**: if "how do they differ" is not a testimony
  contradiction, mark g027 `unsure` and propose another category. That also changes the split.

Write the decision in the `fix` column of both rows.

## Afterwards

- `docs/DISCLOSURE.md`: fill the review table (items, reviewers, date, changes) from
  `apply_review.py --status`.
- `eval/golden/README.md`, `eval/extraction_gold/README.md`: the provenance line becomes "N items
  reviewed by <logins> on <date>; the rest not reviewed".
- Changes to the gold sets change the numbers. The test split was run once
  (`docs/spike/results/test-preregistration-20261028.md`). Report a re-score of the recorded
  answers against corrected gold as a re-score, not as a new run.
