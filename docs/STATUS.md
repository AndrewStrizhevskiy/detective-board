# STATUS

## 2026-10-23 13:00 - orchestrator stopped, handed over to the team

Read `docs/HANDOFF.md` first. Everything is committed and pushed; no background jobs are running.

Done since 2026-10-22: Phase 0 report and ADRs 0001-0008 (`docs/spike/REPORT.md`), retrieval, index builder,
extraction pipeline, graph store, symbolic rules, MCP server, agent, API, UI (redesigned board), golden sets
(64 questions, 43 contradiction cases), security review and quick fixes, team tooling (shards, merge,
CONTRIBUTING, assignments). 424 Python tests + 42 UI logic tests green.

Decisions: bge-m3 (embeddings), qwen3:4b-instruct (answers), qwen3:4b think-off (extraction, prompt v2.1),
hybrid RRF retrieval, SQLite graph.

In progress when stopped: extraction wave 1 on the laptop (26 of 31 chunks of boscombe-valley-mystery done;
cache in `data/extraction/`). Not started: full-corpus extraction, real-data wiring of graph/MCP/rules,
`eval/run_eval.py`, human review of the gold sets, packaging/clean-machine test, slides.

Top risks: full extraction is 24-30 h of CPU (needs strong machines); claims/relations quality is weak;
answers reach the evidence in only about 66-69% of questions (retrieval ceiling); gold sets are AI-written;
demo latency on the laptop is about 40 s to first token.

Deadline: freeze 2026-10-28, show 2026-10-30.
