# ADR-0010: Rule-first deterministic answers and the honesty guard

- Status: Accepted (2026-10-27) for contradiction and alibi routes.
- Date: 2026-10-27
- Deciders: tech-lead, symbolic-layer owner
- Provisional parts: how often the rules find anything on the real graph (unmeasured beyond the curated demo cases); coverage wording of the empty-result sentence.

## Context

When the router picks a rule tool (`find_contradictions`, `check_alibi`) the rule result decides the answer, not the language model. The first real end-to-end run on the laptop (real index, graph of wisteria-lodge, real Ollama; `docs/symbolic-layer.md` 11.1a, STATUS of 2026-10-26) found: the tool returned no finding because the graph had no story days, and the 4B model still wrote that there was no conflict and the self-check passed. That answer took 94 s. An empty rule result is the absence of a finding, not the absence of a conflict.

Coverage at that time (first real run, wisteria-lodge): 107 events and 137 claims in the story graph, 0 with an exact clock time, 0 with a story day, 1 usable presence proposition; R1 examined 19 event pairs and could not decide 16.

## Options

1. **Let the model phrase the rule result** (the old path). Failure observed above. A prompt hint could reduce it but cannot guarantee it with a 4B model.
2. **Keep the LLM path and add a check that rejects consistency claims** when the rule result is empty or failed. Implemented as a guard for the LLM path too (`answer.self_check(..., forbid_consistency=True)`), but it only rejects after the model has spent 40-90 s.
3. **Rule-first deterministic template** (`AgentConfig.rule_first`, default true; `agent/rule_first.py`, `agent/honesty.py`). No model call when a rule tool actually ran:
   - findings: one sentence per finding with rule id, verdict, reason code, label (`derived` or `conditional` with the low-confidence inputs) and verbatim quotes; a `Curated:` line when curated facts are inputs;
   - empty result: `The rule engine found no violation among the facts extracted for <story>. This does not show that the accounts are consistent:` plus coverage numbers (events, claims, events with an exact clock time, events with a story day, claims with a presence proposition, pairs R1 could not decide) and, in the default extractive mode, a `Text evidence:` line (a verbatim sentence the model chose) or the plain nothing-about-this sentence;
   - ambiguous person: what was missing; a skipped or failed tool does not produce this template (the question goes down the text path).

## Decision

Option 3, with the guard of option 2 kept for the LLM path. The words that assert agreement ("no conflict", "consistent", "no contradiction") do not occur outside quoted source text, the negated sentence above, or a `consistent` verdict a rule really returned. Measured effect: the Garcia question went from 94 s and a wrong "no conflict" to 1.6 s and an honest sentence (STATUS 2026-10-26); the recording `web/replay/real-wisteria-r1-curated.json` shows 0.3 s with the curated facts; `web/replay/real-boscombe-control.json` shows the empty-result sentence for the McCarthy/Crowder control (86 events, 107 claims, 4 with an exact clock time, 7 with a story day, 3 presence propositions; R1 examined 18 pairs and could not decide 12) followed by two verbatim text sentences, 19.1 s because of the model's selection call.

## Consequences

- Positive: instant, faithful and repeatable; the answer says what the rules saw and how much they could not see.
- Negative: the answer is a fixed template, not fluent prose; its value depends on the facts in the graph. On real data R1 and R3 still find nothing automatically because exact times and days are missing (ADR-0012); the Wisteria finding in the demo rests on curated facts (ADR-0011).
- The empty-result sentence never claims consistency, so a question whose answer is "no conflict" cannot be confirmed by the system; that is intended.
- Follow-up: the regression tests cover the empty and failed cases; re-check the guard whenever the rule result format changes.
