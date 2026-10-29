# Suspect board: overnight queue, frozen protocol (2026-10-29, written before the queue starts)

The test split (8 stories) was used once, with the protocol of `suspects-prereg-20261029.md`; it is spent. Nothing
below is judged on it. The overnight queue (`scripts/suspects_overnight.sh`) runs new variants on the **dev** split
only (8 stories), plus the share-of-text-read curve on all 16 cases. These numbers are exploratory: there are no
new held-out cases yet (the four Gutenberg texts the user approved are downloaded to `heldout-texts-raw/`, but their
cases, cut points and graph extraction are not built; see README_MORNING.txt).

Frozen scoring parameters for every run: matrix lam 1.0, kind bonus 0.5, min support 2, margin 1.0; a judge that
reports confidence `low` abstains; self-consistency confidence = agreement on the top answer (>= 0.8 high, >= 0.6
medium, else low). No threshold is tuned in the queue. Ensembles over finished open-name judges: `ens_vote_all`
(the top answer needs at least two votes and strictly more than the runner-up) and `ens_agree_all` (all answering
judges name the same top candidate, at least two of them). Reduced-cut runs are excluded from ensembles.

Queue: thinking mode on qwen3:8b; qwen3:14b q4 (pull approved by the user, ~9.3 GB); case-file dossier method;
pairwise tournament (top 6 not-police-accused candidates plus NO_PERSON, both orders, Copeland); self-consistency
with 7 samples at temperature 0.3; cuts at 60, 75 and 90 percent of the pre-cut text; two candidate-order
shuffles; other seeds (run-to-run noise); then 14B variants and more seeds while time remains (deadline 07:00
server time).

Primary claim (unchanged): the system does not accuse the innocent. Secondary: culprit first, top 3, MRR, abstention,
with Wilson 95 % intervals. Dev has 8 cases, so every difference below one or two cases is noise.
