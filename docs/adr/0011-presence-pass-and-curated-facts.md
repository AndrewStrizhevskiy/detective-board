# ADR-0011: Targeted presence pass and curated demo facts

- Status: Accepted for the curated demo facts; the automatic presence pass is Proposed (precision unmeasured, to be measured on the department server).
- Date: 2026-10-27
- Deciders: tech-lead, demo-director
- Provisional parts: precision and recall of automatic presence facts (unmeasured); the human re-check of the curated file (done 2026-10-29 by LitrumCoder).

## Context

Rules R1 and R3 consume "person at place at time" propositions. The generic extraction (ADR-0012) does not produce them in usable form on real data. Two attempts to extract them directly with a small model were made.

| Attempt | Setup | Result |
|---|---|---|
| presence-1 (STATUS 2026-10-26 night) | three c001 chunks; qwen3:4b-instruct 16 facts, qwen3:8b 12 facts | strict grounding kept 0, lenient kept 2: models wrote pronouns ("he") as the person |
| presence-2.1 (graph candidate lists as JSON-schema `enum` for person and place, carry-over from earlier chunks) | the same three c001 chunks | qwen3:4b-instruct 7 facts, 1 kept (one chunk truncated); qwen3:8b 15 facts, 11 kept, with the key fact right and several wrong persons or places |

The presence-2.1 counts come from the run reported by the team lead and are not stored in a committed result file; the precision of the kept facts is unmeasured.

Corpus constraint: no R3 positive with an explicit person, place and time exists in the corpus (`docs/HANDOFF.md` section 0). Gold c042 (the McCarthy/Crowder control) is weaker than its label: its disagreement is about intent, not presence.

## Options

1. **Rely on generic claims.** Fails (ADR-0012).
2. **Presence pass only, automatic.** presence-2.1 with qwen3:8b is the best so far, but 11 kept facts with several wrong persons or places cannot back a demo finding, and the 4B model keeps 1 of 7.
3. **Curated facts for the demo cases plus the automatic pass reported separately.** `data/curated/presence_demo.jsonl` has five facts, each tied to a verbatim quote (the loader refuses quotes that are not verbatim spans of `data/clean/<story>.txt`): two for c001 (Eccles and Baynes, the R1 case) and three for the Boscombe control (c041/c042). Facts are marked `curated: true`, `curated_by` "team (prepared with tooling support, to be re-checked by a human)", `inferred` slots and `confidence: low` where coreference was done by hand. The label appears in the graph, the Explanation summaries `(curated)` and a `Curated:` line in the answer.

## Decision

Option 3 for the demo, and keep option 2 as the automatic route to be measured on the server (qwen3:8b and qwen3:4b-instruct, presence-2.1, demo stories first). A result that rests on curated facts is never reported as an extraction result. The finding stays `conditional`: curation does not make a fact true. What would change the decision: a server measurement showing automatic presence facts with precision high enough for the Wisteria case.

## Consequences

- The demo finding (R1 on Garcia) shows what the rules do when the facts are right, not what a model finds alone. This must be said on stage (`docs/design/demo-script.md`, `docs/DISCLOSURE.md`).
- The curated file was re-checked by a human on 2026-10-29 (LitrumCoder, `docs/spike/results/curated-review-2026-10-29.md`). The c001 Baynes fact has person and place resolved by the team from the preceding line, and "since one o'clock" is stored as the instant 01:00.
- No R3 positive exists with curated data: the Boscombe facts serve as a control that R1 must not flag; intent is not encoded.
- Automatic presence precision stays unmeasured until the server run; no number may be quoted for it.
