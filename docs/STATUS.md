# STATUS

## 2026-10-27 morning

Read `docs/HANDOFF.md`, `docs/ROADMAP.md`, `docs/spike/REPORT.md` (Addendum 2026-10-27) and ADR-0009..0012. Server plan: `docs/team/SERVER_RUNBOOK.md`.

State
- Main answer path for text questions is extractive: the model only chooses numbered sentences, the answer is verbatim; 8-20 s per question instead of 45-140 s (ADR-0009; 12 questions, one run: `docs/spike/results/api12-20261027-*.md`). g001 answered, g056/g057/g047 refused, g007/g016 still NONE, Russian refused by the gate. The 4B model is wording-sensitive: do not edit the selection prompt without re-measuring.
- Contradiction and alibi questions are answered rule-first with no model call; an empty rule result gives an honest sentence with coverage and text evidence, never "no conflict" (ADR-0010).
- Demo cases use five curated, human-checked-pending presence facts (`data/curated/presence_demo.jsonl`), marked "curated" in the answer (ADR-0011). No R3 positive with person, place and time exists in the corpus; c042 is weaker than its label (intent).
- Generic extraction prompt stays `extract-2.1` with a deterministic repair (ADR-0012). On real data R1/R3 find nothing automatically: first real run wisteria-lodge 107 events, 137 claims, 0 exact times, 0 days, 1 usable proposition, R1 examined 19 pairs and could not decide 16.
- Presence pass: presence-1 failed (pronouns); presence-2.1 on the three c001 chunks: qwen3:4b-instruct 7 facts / 1 kept, qwen3:8b 15 facts / 11 kept, several wrong persons or places. Precision unmeasured.
- TTFT: prefill about 21 tok/s, only the system-prefix cache helps. LLM composition is no longer in the main demo path.
- Five real recordings in `web/replay/real-*.json` (recorded 2026-10-27 at commit d9709d0).

Server (i7-12700K, 96 GB, RTX 4070 12 GB, ours until 2026-11-01): slots Tue 27 from 14:30 and Wed 28 12:00-18:00; organizers approved precomputing elsewhere; freeze Wed 18:00. The laptop cache (231 chunks, 8 stories) seeds the run. Order: bootstrap, determinism, generic extraction of 596 chunks with v2.1 (compare qwen3:8b on gold12 first), `just graph`, presence-2.1 on demo stories, contradictions eval.

Open: precision of automatic presence facts; exact-time/day counts on the full graph; human re-check of curated facts and gold sets; rehearsals with the final code.
