# Real API run of the 12 control questions (generative path with decline-retry), 2026-10-27

Real stack on the target laptop: real index (596 chunks), graph of 8 stories (231 chunks) + curated demo facts, live bge-m3 query embeddings,
qwen3:4b-instruct (think off), `rank_full` context (about 1000 tokens), commit `fix/decline-retry` merged to main. One run, temperature 0, seed 42.
Script: ad-hoc client over `POST /api/ask` (same as the UI). This is the baseline BEFORE the extractive answer mode.

| id | category | expected | route | status | verified | first token s | total s | answer (first 90 chars) |
|---|---|---|---|---|---|---|---|---|
| g001 | fact | answer | vector | partial | True | 0.7 | 7.3 | I could not compose a verified answer, but these passages from the sources are the closest |
| g007 | fact | answer | vector | partial | True | 38.9 | 45.7 | I could not compose a verified answer, but these passages from the sources are the closest |
| g028 | testimony-contradiction | answer | mcp,graph,vector | answered | True | 0.4 | 0.4 | The rule engine found no violation among the facts extracted for boscombe-valley-mystery.  |
| g032 | testimony-contradiction | answer | vector | answered | True | 37.1 | 54.2 | Holmes disproved that the assailant tore the paper from the dead man’s hand, because if th |
| g016 | relation | answer | graph,vector | partial | False | 38.1 | 140.8 | The relationship between James Barclay and Nancy Barclay was that James Barclay married he |
| g019 | relation | answer | graph,vector | partial | False | 40.0 | 106.3 | Mr. Blessington was really Sutton . [4: "Then Blessington must have been Sutton."]  [UNVER |
| g022 | chronology | answer | mcp,graph,vector | answered | True | 0.2 | 0.2 | The rule engine could not answer this question: check_alibi was not run: no person found i |
| g038 | alibi | answer | vector | answered | True | 36.8 | 68.4 | Holmes ruled out Fitzroy Simpson because powdered opium would be detectable in curry, and  |
| g047 | out-of-corpus | refuse | vector | refused | True | None | 0.1 | In these materials there is nothing about this. |
| g056 | out-of-corpus | refuse | vector | partial | True | 42.9 | 50.0 | I could not compose a verified answer, but these passages from the sources are the closest |
| g057 | adversarial | correct_premise | vector | partial | True | 38.8 | 45.7 | I could not compose a verified answer, but these passages from the sources are the closest |
| g062 | language-ru | answer | vector | refused | True | None | 0.2 | In these materials there is nothing about this. |

Observations (honest):
- g001, g007 (facts): 'closest passages' (status partial) instead of a composed answer: the 4B model declines even after the firm retry; the answer sentence is shown as a quote.
- g028 and g022 were routed to the rule-first template although they are text questions: the rule engine could not answer them (regression fixed in the next branch).
- g056, g057 (out of corpus / false premise) became 'closest passages' instead of a plain refusal (the decline fallback applied to them).
- g047 is refused by the gate in 0.1 s; g062 (Russian) is refused by the gate.
- Cached prompts return in seconds (Ollama reuses the whole KV cache for an identical prompt): g001 7 s.
- This is n=12, one run, a crude look; not a quality measurement.
