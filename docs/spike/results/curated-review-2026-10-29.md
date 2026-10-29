# Curated facts and scene: AI pass and human re-check (2026-10-29), issue #22

Two steps on 2026-10-29. First, an AI assistant (Claude, working for LitrumCoder) made the pass
below and corrected five notes. Then **LitrumCoder (human)** read every record, its story context
and the table below, and found no mismatch. Both files now carry `reviewed_by: LitrumCoder` and
`reviewed_on: 2026-10-29`. Screens, answers and slides say "human re-check done by LitrumCoder on 2026-10-29"
(`curated_schema.CURATED_REVIEW`, kept equal to the files by `tests/curated/test_review.py`).

Files: `data/curated/presence_demo.jsonl` (8 facts), `data/curated/scenes.jsonl` (1 scene).
Method: each quote was located in `data/clean/<story>.txt` by a script, and all 9 are verbatim.
Then the surrounding text (about 1-3 kB before and after) was read for the five questions of the
issue: (1) the quote says what the note says; (2) the inferred slots are justified; (3) the
speaker is right; (4) a relative-time reading is fair; (5) the fact is not stronger than the text.

| # | id | 1 | 2 | 3 | 4 | 5 | Result |
|---|---|---|---|---|---|---|---|
| 1 | c001-eccles-garcia-bedroom | yes | yes: Eccles was the guest at Wisteria Lodge ("the end of my visit to Wisteria Lodge", same chunk) | yes (Eccles) | n/a | yes, LOW; see the finding below | note corrected |
| 2 | c001-baynes-garcia-common | yes | yes: "He" is "the man" of Holmes's question, "there" is Oxshott Common from Gregson's line | yes: Eccles answers "perfectly impossible, Mr. Baynes" | n/a | yes, LOW | note corrected (day key) |
| 3 | c042-holmes-ross-morning | yes | yes: "He" is McCarthy from the sentence before | yes: Holmes states the facts to Watson in the train | n/a | yes | accepted |
| 4 | c042-holmes-hatherley-afternoon | yes | nothing inferred | yes (Holmes) | n/a | yes; "left his house" is the moment of leaving | note extended |
| 5 | c042-james-father-at-ross | yes | yes, LOW | yes (James at the inquest) | n/a | yes; it is hearsay from the maid | note extended |
| 6 | c002-lady-chair-at-entry | yes | yes: "me" is the speaker | yes (Lady Brackenstall to Holmes) | the moment is stated in the quote | yes, LOW | accepted |
| 7 | c002-crocker-window-at-entry | yes | yes: "her" is Mary Fraser, Lady Brackenstall | yes (Captain Crocker's confession) | fair: both describe Sir Eustace entering the dining-room; it is the curator's reading, LOW | yes | accepted |
| 8 | c001-eccles-own-bedroom | yes | yes (speaker, Wisteria Lodge as in 1) | yes | n/a | yes, LOW; see the finding below | note corrected |
| 9 | wisteria-oxshott-one-oclock (scene) | yes | yes (place and victim from Gregson's line) | n/a | n/a | the window is the instant 01:00, narrower than "since one o'clock" (death "before the rain"); declared in the note | accepted |

Counts: 9 checked, 0 removed, 4 accepted as written, 5 notes corrected or extended. No slot, time,
place, person or confidence value changed, so no rule result changes.

## Finding that matters for the demo (facts 1 and 8)

The time "nearly one o'clock" is **Garcia's own words**, reported by Eccles. In the solution Holmes
reads them as a deliberate alibi: "when Garcia went out of his way to tell him that it was one it
was really not more than twelve". The R1 conflict of gold c001 is real in the text (Eccles himself
calls it "perfectly impossible"). The story resolves it by showing that Garcia's stated time was
false, not that one man was in two places. The notes now say this. If the jury asks "so where was
Garcia really?", the answer is: the rule shows that the two testimonies cannot both be true. The
story's own answer is that Garcia lied about the time; the system does not decide which testimony
is false.
