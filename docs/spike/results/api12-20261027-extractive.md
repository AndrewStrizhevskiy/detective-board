# Real API run of the 12 control questions (extractive answer mode), 2026-10-27

Same setup as `api12-20261027-generative.md` (real index, graph of 8 stories + curated facts, live bge-m3 embeddings, qwen3:4b-instruct),
but the model only CHOOSES one or two numbered sentences (JSON schema enum, tested wording of the selection prompt); the answer is those sentences verbatim.

| id | category | expected | route | status | verified | total s | answer (first 100 chars) |
|---|---|---|---|---|---|---|---|
| g001 | fact | answer | vector | answered | True | 9.3 | From the sources: [1: "“It is a swamp adder!” cried Holmes; “the deadliest snake in India."] |
| g007 | fact | answer | vector | refused | True | 10.9 | In these materials there is nothing about this. |
| g028 | testimony-contradiction | answer | mcp,graph,vector | answered | True | 16.4 | The rule engine found no violation among the facts extracted for boscombe-valley-mystery. This does  |
| g032 | testimony-contradiction | answer | vector | answered | True | 15.8 | From the sources: [2: "“Before going into this, I would draw your attention to the fact that, if Ale |
| g016 | relation | answer | graph,vector | refused | True | 14.5 | In these materials there is nothing about this. |
| g019 | relation | answer | graph,vector | answered | True | 8.1 | From the sources: [4: "This so-called Blessington is, as I expected, well known at headquarters, and |
| g022 | chronology | answer | mcp,graph,vector | answered | True | 17.5 | From the sources: [1: "It lasted forty minutes, and at a quarter-past nine Mrs. Barclay returned hom |
| g038 | alibi | answer | vector | answered | True | 20.2 | From the sources: [1: "By no possible supposition could this stranger, Fitzroy Simpson, have caused  |
| g047 | out-of-corpus | refuse | vector | refused | True | 0.2 | In these materials there is nothing about this. |
| g056 | out-of-corpus | refuse | vector | refused | True | 19.4 | In these materials there is nothing about this. |
| g057 | adversarial | correct_premise | vector | refused | True | 14.9 | In these materials there is nothing about this. |
| g062 | language-ru | answer | vector | refused | True | 0.2 | In these materials there is nothing about this. |

Comparison with the generative path (previous file): answered quickly (8-20 s per question instead of 45-140 s), out-of-corpus questions are refused again (g056, g057, g047),
g001 is answered with the verbatim swamp-adder sentence. Still not answered: g007 and g016 (the model chooses NONE), g062 (Russian: refused by the gate).
Caveats: n=12, one run; 'answered' means a selected sentence quoted verbatim, which is NOT the same as a correct answer: g028's rule line says 'no violation found' and
its text evidence is whatever the selection picked; every answer must be read by a human. The 4B model is sensitive to the exact wording of the selection prompt:
a rewording of one clause flipped g001 from the right sentence to NONE (see the commit history); do not edit the prompt without re-measuring.
