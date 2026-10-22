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
