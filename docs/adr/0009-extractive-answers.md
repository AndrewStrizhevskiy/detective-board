# ADR-0009: Extractive answers (the model chooses sentences)

- Status: Accepted (2026-10-27) as the default answer mode for the text routes; the 12-question evidence is a pilot (n=12, one run).
- Date: 2026-10-27
- Deciders: tech-lead
- Provisional parts: the selection prompt wording (frozen, see Consequences); the share of questions that end in NONE; quality of the chosen sentence is not judged by a human. Refines ADR-0008 (the answer model stays qwen3:4b-instruct; what it is asked to do changes).

## Context

On the target laptop prefill runs at about 21 tokens/s and only the system-prefix cache helps (`docs/perf/ttft-levers-2026-10-26.md`: 42.7 s to prefill the 1080-token g001 prompt with the prefix cached, 52.7 s without; threads, batch and num_ctx change nothing beyond noise). The answer check of 2026-10-23 measured 42.0 s to the first token and 59.5 s per question (`docs/spike/results/answers-20261023-v3.md`, ADR-0008).

The first real run of the 12 control questions through the API with the generative path (after the decline-retry fix) showed a second problem besides speed: the 4B model declines even when the answer is in the prompt (`docs/spike/results/api12-20261027-generative.md`).

| Generative path, 12 questions, one run | Result |
|---|---|
| g001, g007 (facts) | `partial`: "I could not compose a verified answer, but these passages ... are the closest" (g001 7.3 s only because Ollama reused a cached prompt) |
| g056, g057 (out of corpus / false premise) | became `partial` "closest passages" instead of a plain refusal: the decline-retry plus fallback turned refusals into passages |
| g016, g019 | `partial`, 106-141 s total, answer carried unverified text |
| g032, g038 | answered, 54.2 s and 68.4 s total |
| total time of questions that called the model | 45.7-140.8 s |

## Options

1. **Generative with decline-retry and closest-passages fallback** (the path above). Measured: fragile, slow (45-141 s), refusals of out-of-corpus questions degraded into passages.
2. **Larger model (qwen3:8b).** Measured earlier: 101.1 s to the first token, at most one question better (ADR-0008, REPORT section 9). Rejected on the laptop.
3. **Extractive mode.** The agent numbers the candidate sentences of the retrieved excerpts (per source the best 6 by the IDF window scorer, at most 24 in all, in source order, `S1`, `S2`...). One short call, constrained by an Ollama `format` JSON schema (`choice` and optional `second`, each an id or `NONE`), returns one or two ids. The answer text is a template, `From the sources: [n: "sentence"]`, verbatim by construction, labelled `source_text`. `NONE`, an unknown id or unparsable output is a plain refusal with code `no_evidence`; there is no retry and no closest-passages fallback. The out-of-corpus gate runs first and is unchanged (`docs/api.md`).

Measured for option 3 (`docs/spike/results/api12-20261027-extractive.md`, same 12 questions, real index, graph of 8 stories plus curated facts, qwen3:4b-instruct):

| Aspect | Generative | Extractive |
|---|---|---|
| time per model-calling question | 45.7-140.8 s | 8.1-20.2 s |
| g001 | partial (closest passages) | answered, 9.3 s, verbatim swamp-adder sentence |
| g056, g057, g047 (refuse expected / correct premise) | partial, partial, refused | refused, refused, refused |
| g007, g016 | partial | refused (model chose NONE) |
| g062 (Russian) | refused by the gate | refused by the gate |

The recording `web/replay/real-g001-agent.json` (commit d9709d0) shows g001 answered in 10.8 s.

## Decision

Make `answer_mode = extractive` the default (`AgentConfig.answer_mode`); keep `generate` for A/B comparison. The model only chooses; it never composes text. Every answer is therefore a verbatim sentence from the corpus, and the quote self-check passes by construction. The measurement that would reverse this: a human-judged comparison on a larger set in which composed answers are clearly better and still verified.

## Consequences

- Positive: 8-20 s per question instead of 45-140 s, so the time-to-first-token worry (`docs/design/demo-script.md`) is gone for the main demo steps; no composed text means no hallucinated wording; out-of-corpus questions are refused plainly.
- Negative: answers are one or two quoted sentences, not prose; a sentence can be verbatim and still not be the best answer. "Answered" is not "correct": g032 and g038 were answered, but nobody has judged whether the sentence is right. g007 and g016 stay unanswered (NONE); g062 (Russian) stays refused by the gate.
- The 4B model is wording-sensitive: a rewording of one clause of the selection prompt flipped g001 from the right sentence to NONE (commits ba6f773, 40ee6c3). The prompt text is frozen at the tested wording; do not edit it without re-running the 12 questions.
- Limits: n=12, one run, temperature 0, seed 42, no human judging, gold generated automatically. These are pilot numbers.
- Not measured: precision of the chosen sentence against gold on a larger set; behaviour of the 8B model in this mode; behaviour on the department server.
