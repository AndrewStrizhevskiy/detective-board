# Suspect board: fresh held-out confirmation, frozen protocol (2026-10-30, written before any run on these cases)

Purpose: one honest confirmation of the best dev method of the overnight queue, on cases nothing was tuned on.
No parameter, method or case is chosen after seeing a result on these cases.

## Cases
Source: Project Gutenberg #204, *The Innocence of Father Brown* (`https://www.gutenberg.org/cache/epub/204/pg204.txt`,
477,688 bytes; sha256 in `eval/suspects/heldout_manifest.json`). The user chose this text, together with three others,
in the chat on 2026-10-29 before it was downloaded. Six stories, `eval/suspects/heldout_cases.jsonl`, built by
`eval/suspects/prepare_heldout.py`: The Hammer of God, The Invisible Man, The Secret Garden, The Eye of Apollo,
The Three Tools of Death (no murderer: an accident; the accused man is the 'innocent'), The Wrong Shape. Culprit,
cleared persons, victim and the cut (the start of the paragraph before the explanation) come from reading each
story's ending; **they are automatically marked and need a human check** (`solvable` = partly for all).
Not used: the three novels the user also approved (Styles, Sign of the Four, Study in Scarlet). They are real
whodunits, but the text before the reveal (277k, 72k and 102k characters) does not fit the 14,336-token context of
the frozen method; the model would silently drop the start of the story.

## Candidates
The same extractor as for the main corpus (qwen3:4b, prompt `extract_v2_1`, schema v2, temperature 0, seed 42) on the
102 chunks before the cuts only, into `data/graph/heldout.sqlite`; the same `build_candidates` (graph mentions before
the cut, Holmes/Watson/role words and the victim of the question dropped, cap 12, plus NO_PERSON). The graph is not
normalised (not needed for persons). A culprit who is not named before the cut is unreachable; that is reported.

## Methods, run once, exact parameters
- `pairwise_14b_open`: `qwen3:14b`, pairwise tournament over the top 6 not-police-accused candidates plus NO_PERSON,
  both orders, Copeland score, `--num-ctx 14336 --seed 42 --pair-k 6`, temperature 0. The method never abstains.
- Baselines: `most_mentioned`, `most_accused`, `prior` (no model); `fulltext_14b_open` (same model and context, abstains
  when it says confidence low); `bare` (qwen3:8b, question and candidates only, as on dev).
- Scoring: top-1, top-3, MRR, cleared-accused (innocent first), wrong total, abstention, Wilson 95 % intervals,
  `eval/suspects_run.py score` with the defaults of `suspects-prereg-20261029.md`.

## Claim and limits
Main claim: the system does not accuse the innocent; not that it finds the culprit. With six cases every interval is
wide. Dev numbers (8 cases, method chosen on them) are exploratory and optimistic. Failures are reported as they are.
