# STATUS

## 2026-10-26 night (orchestrator resumed; all actions pre-approved by the team lead)

Read `docs/HANDOFF.md` and `docs/ROADMAP.md`; server plan: `docs/team/SERVER_RUNBOOK.md`.

Merged into `main` today: field repair for extracted items, targeted presence pass, symbolic-readiness report and the
v2.2 prompt experiment (NOT adopted), department-server scripts (bootstrap with confirmation, run-all, progress, report),
config defaults/warm-up/Python 3.12/preflight (PR #11), rule-first deterministic answers for contradiction and alibi
questions, CI lint fix. 606 Python tests, 51 UI logic tests, ruff and pyright clean.

Decisions
- Generic extraction prompt stays `extract-2.1` (v2.2 was worse on entities 0.51 vs 0.56 and relations 0.06 vs 0.14; its
  better polarity is reproduced by the deterministic repair). Cache entries made with v2.1 remain valid.
- Rules get their input from the separate presence pass, not from generic claims.
- Contradiction/alibi answers are templates built from the rule result (no LLM): instant, faithful, honest about gaps.
- Organizers approved precomputing on other hardware. Server: i7-12700K, 96 GB, RTX 4070 12 GB, own it Oct 26-Nov 1,
  slots Tue 27 Oct from 14:30 and Wed 28 Oct 12:00-18:00. Freeze moved to Wed 18:00.

First real end-to-end run (laptop, real index, graph of wisteria-lodge, real Ollama)
- Fact/contradiction routes work mechanically; the old LLM answer to the Garcia question wrongly said "no conflict"
  (94 s). Now: 1.6 s and honest: 107 events and 137 claims in the story graph, 0 with an exact clock time, 0 with a story
  day, 1 usable presence proposition; R1 examined 19 pairs and could not decide 16.
- Real raw extraction quality (qwen3:4b, 64 chunks, v2.1): participants empty in 178/178 events, `polarity=deny` in 98% of
  claims, time/place copied from the chunk start. The repair step fixes participants (0 -> 122 of 177), denial share
  (98% -> 16%) and demotes copied time/place, but R1/R3 still find nothing without exact times and days.
- Presence pass (prompt presence-1) on the three c001 chunks: qwen3:4b-instruct 16 facts and qwen3:8b 12 facts, strict
  grounding kept 0, lenient kept 2: the models write pronouns ("he") as the person. Fix in progress: presence-2 with
  per-chunk candidate lists (names from the graph as a JSON-schema enum).
- Prefill speed on the laptop is about 21 tokens/s regardless of threads/batch/ctx; only the system-prompt prefix cache
  helps (8-10 s). Expect 43-50 s to the first token for LLM answers (docs/perf/ttft-levers-2026-10-26.md).

Plan for the server session (Tue 14:30): see the TL;DR at the top of `docs/team/SERVER_RUNBOOK.md`. Order: bootstrap ->
determinism -> generic extraction of all 596 chunks with v2.1 (models: qwen3:4b, compare qwen3:8b on gold12 first) ->
`just graph` -> presence pass presence-2 (qwen3:8b and qwen3:4b-instruct) on demo stories, then all -> contradictions eval.

Risks: R1/R3 on real data depend on the presence pass (unmeasured until the server run); AI-written gold sets; 40-50 s
LLM answers on the laptop; extraction caches mix CPU (laptop) and GPU results (same keys, tiny numeric differences).
