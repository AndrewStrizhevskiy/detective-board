# Golden question set

`questions.jsonl` holds 64 questions about the 20 stories in `data/clean/*.txt`.

## Provenance and status: needs human review

The questions, expected answers and gold quotes were written by a Claude agent
(eval-engineer role) from reading the text in `data/clean/`, not from memory of
the canon. Nothing has been reviewed by a human yet. The validator proves only
that each quote is a verbatim substring of its story. It does not prove that the
quote supports the expected answer, that the answer is complete, or that the
question is well posed.

A human must spot-check at least 10 items before any metric computed from this
file is reported as a result. Suggested minimum: the 8 least certain items below
plus 2 or more others picked at random.

Stories fully read: abbey-grange (key passages), beryl-coronet, black-peter,
blue-carbuncle, boscombe-valley-mystery, crooked-man, man-with-the-twisted-lip,
musgrave-ritual, red-headed-league, reigate-squires, resident-patient,
scandal-in-bohemia, silver-blaze, speckled-band. Only grepped or partly read:
copper-beeches, naval-treaty, norwood-builder, priory-school, thor-bridge,
wisteria-lodge (no question depends on more than a few passages; priory-school,
copper-beeches and wisteria-lodge have no gold quotes at all, so they are
under-represented).

## Fields

| field | meaning |
|---|---|
| `id` | unique, `g001`... |
| `category` | fact, multi-hop, relation, chronology, testimony-contradiction, alibi, cross-story, out-of-corpus, adversarial, language-ru |
| `lang` | `en` or `ru` (question language; the corpus is English) |
| `question` | text sent to the system |
| `expected_answer` | short reference answer; for refusals, the expected behaviour |
| `expected_behavior` | `answer`, `refuse`, `correct_premise`, `ignore_injection_and_answer` |
| `gold_quotes` | list of `{story, quote}`; story is the file stem in `data/clean/`; quote is verbatim after whitespace normalisation |
| `answerable` | true if the corpus supports an answer (including a corrected answer for false premises) |
| `notes` | rationale and a `confidence=` tag from the author |

Counts: fact 8, multi-hop 6, relation 5, chronology 7, testimony-contradiction 8,
alibi 5, cross-story 5, out-of-corpus 12, adversarial 5, language-ru 3.

## Validation

    python3 scripts/eval/validate_golden.py

Checks JSON, required fields, unique ids, category counts, answerable/refusal
consistency and that every quote is found in its story. Exit code 1 on any problem.

## Items the author is least sure about

- `g029` (Red-Headed League dates): this is an inconsistency inside the text
  (ad dated April 27, "two months ago", narrator says autumn, card dated October 9),
  not a witness conflict. The expected answer could be argued as a printing
  or editing artefact rather than a "contradiction". Lowest confidence.
- `g036` (McFarlane alibi): I read his statement and the newspaper time of the
  fire, but did not read the rest of the story, so I do not know whether the
  text later confirms or refutes his whereabouts. Answer states only what he claims.
- `g015` (Neligan, Carey, Cairns): the text never names the man Carey threw
  overboard; the link to Neligan's father is inferred by the reader.
- `g042` (bogus advertisement): fits Black Peter cleanly but only loosely
  Blue Carbuncle, where the advertisement finds Baker, not the culprit.
- `g055` and `g056` (Horner's verdict, Holmes's fee for Silver Blaze): marked
  unanswerable because I found no such statement; these "absence" claims were
  checked with `rg` on keywords only, a human should confirm.
- `g045`-`g054` (out-of-corpus): absence of key names was checked with `rg`.
  `g045` (Moriarty) is risky because "Moriarty" occurs once in norwood-builder.
  `g054` (1890 Prime Minister) is a real-world question that a bare LLM would
  answer correctly; it is intended to test refusal-to-ground, so decide whether
  that is the behaviour you want to score.
- `g037` (Thor Bridge): the story uses straight quotes and double spaces; I read
  only the opening and the middle of this story.
- `g059` and `g061` (prompt injection): `expected_answer` describes behaviour
  rather than a single string, so scoring needs a rubric or a judge, not exact match.
- `g062`-`g064` (Russian): the expected answers are my own translations.

## Contradiction and alibi finding set (`contradictions.jsonl`)

Separate from `questions.jsonl`. It measures whether the system FINDS a
contradiction, not whether it answers a question well. Reported separately from
answer quality (faithfulness, citation correctness, refusal rate, recall).

### Provenance and status: needs human review

Written by a Claude agent (eval-engineer role) from reading the story text in
`data/clean/`, not from memory of the canon. No human has reviewed it. The
validator proves only that each quote is a verbatim substring of its story and
that counts and labels are internally consistent. It does not prove that the
quotes make the claimed contradiction, or that a control is really consistent.
A human must spot-check at least 10 items (all of the least-sure items below
plus a few random ones) before any metric from this file is reported as a result.

### Items

43 items, one story-level case each. Fields:

| field | meaning |
|---|---|
| `id` | `c001`... |
| `story` | file stem in `data/clean/` |
| `kind` | `R1_place_conflict` (a person in two places at overlapping times), `R2_order_cycle_or_inconsistency` (event order or dates inconsistent), `R3_claim_vs_fact` (a witness claim incompatible with an established fact), `consistent_control` (looks suspicious, text is consistent) |
| `question` | prompt for the system, e.g. "Is there a conflict about ...?" |
| `expected_finding` | true = text contains a contradiction; false for controls |
| `expected_description` | one-paragraph gold explanation |
| `involved_claims` | list of `{who, what, quote}`; quote is verbatim after whitespace normalisation. For controls these are the statements that only look conflicting |
| `evidence_strength` | `explicit` = the text states or directly shows the conflict; `inferred` = the reader or Holmes has to derive it |
| `needs_time_normalisation` | true when the case depends on clock or date arithmetic ("quarter to nine", weekday arithmetic) |
| `notes` | rationale and a `confidence=` tag |

Counts: R1 4, R2 3, R3 19, controls 17 (26 positives, 17 controls); 11 items need
time normalisation; 11 are `inferred`.

Honest limits of the corpus: the requested 5 R1 cases do not exist as clean cases.
Only `wisteria-lodge` (Garcia at about one o'clock) is a textbook
person-in-two-places conflict; `abbey-grange` is close; the `norwood-builder` and
`reigate-squires` R1 items are borderline (their "two places" come from contested
evidence or from Holmes's reasoning) and are labelled `confidence=low`. I did not
invent more. The R2 set is also thin: one solid item (`red-headed-league` dates),
one resolved slip (`reigate-squires`), and one weak one (`boscombe-valley-mystery`).

### Validation

    python3 scripts/eval/validate_contradictions.py

Checks JSON, fields and types, unique ids, kind and `expected_finding` agreement,
quote presence (every `involved_claims` quote must be found in its story), at least
2 quotes per item and minimum counts per kind (R1 >= 4, R2 >= 3, R3 >= 8, controls
>= 8, total >= 24). Exit code 1 on any problem.

### Metrics

A system answer for each item is reduced to: `found` (did it report a
contradiction, yes/no) and `explanation` (free text with cited passages). Item-level
means one decision per item, not per sentence.

- Detection precision = TP / (TP + FP), recall = TP / (TP + FN), F1 = 2PR / (P + R).
  A positive item (`expected_finding=true`) answered `found=yes` is TP, answered
  `no` is FN. A control answered `found=yes` is FP, answered `no` is TN. Report
  overall and per `kind`; also split by `evidence_strength` and by
  `needs_time_normalisation`, because the rule layer and the LLM are expected to
  fail differently there.
- False-positive rate on controls = FP / (number of controls) = FP / (FP + TN).
  Reported on its own, since F1 hides it when positives dominate (26 vs 17).
- Explanation correctness, only over items where the system said `found=yes` on a
  positive item (the TPs): an explanation is correct if it cites the gold
  contradiction, operationalised as: it quotes or points to at least all
  `involved_claims` marked as the conflicting pair (default: at least 2 of the gold
  quotes, matched by normalised substring or by a judge against `expected_description`).
  Report the share of TPs with a correct explanation. A right yes with wrong
  evidence counts as TP for detection but incorrect for explanation.
- Not mixed with answer quality: these numbers are never averaged with the
  `questions.jsonl` metrics, and a run reports both tables.

Not defined here: exact matching rules for the judge, and the per-rule (R1/R2/R3)
attribution of the neuro-symbolic layer; add them when the layer exists.

### Items the author is least sure about

- `c003` (Norwood hotel vs hall thumb-mark) and `c004` (Reigate, Alec's position):
  borderline R1; the conflict is built from contested evidence and Holmes's
  reasoning. Could be R3 or not a positive at all.
- `c007` (Boscombe, "morning" return vs three o'clock departure): weakest
  positive. "Morning" may be loose and nobody in the text flags it.
- `c006` (Reigate quarter to twelve vs quarter to one): a deliberate ruse by Holmes
  that the text calls a slip. Positive as a time conflict, but a human may prefer to
  call it a control.
- `c028`, `c043` (Silver Blaze overcoat and the Barclay evening times): controls
  that rest on loose wording; a strict reader may call either a small slip.
- `c042` (Boscombe game-keeper "following"): a control about belief vs denial. It
  disagrees with `g027` in `questions.jsonl`, which treats the same pair as a
  conflict. Labelling decision for a human.
- `c024` (Copper Beeches "gone to America"): I only saw Holmes's paraphrase, not
  the passage where the story first tells it.
- `c017` ("John Robinson"): trivial.
- `c033` (Abbey Grange "about a year" vs eighteen months) and `c041` (Boscombe
  Cobb the groom): controls that need a small inference (story date; "serving-man"
  equals "groom").
- Coverage: read end to end: norwood-builder, silver-blaze, thor-bridge,
  priory-school, abbey-grange, crooked-man. Read roughly the first two thirds only:
  wisteria-lodge, man-with-the-twisted-lip, boscombe-valley-mystery, and
  blue-carbuncle from the Alpha Inn onward. Read in targeted passages or grepped:
  reigate-squires, naval-treaty, red-headed-league, black-peter, resident-patient,
  beryl-coronet, copper-beeches, speckled-band, scandal-in-bohemia, musgrave-ritual.
  Contradictions elsewhere in those stories may be missing.
