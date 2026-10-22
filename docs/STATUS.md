# STATUS

## 2026-10-22 (evening) - Phase 0 almost done, Phase 1 started

Done
- Corpus: 20 stories, 596 chunks with source anchors (data/chunks.jsonl), licence notes in data/LICENSES.md.
- LLM speed (clean runs, CPU only): 4B models 7.0-7.8 tok/s, qwen2.5:7b 4.9, qwen3:8b 4.3; 15-30 s to first token on a 300-word prompt.
- Embeddings: bge-m3 is the only one that answers Russian questions (story-level hit@5 1.00 vs 0.00-0.20); chunk-level comparison pending.
- Extraction pilot (12 hand-labelled chunks, labels by a Claude agent): qwen3:4b-instruct, gemma3:4b, qwen3:8b scored; qwen2.5:7b, phi4-mini, qwen3:4b running.
- Docs: PRD, acceptance, architecture, ADR 0001-0004, symbolic layer spec, test plan, demo script, jury FAQ.
- Eval: golden questions (64), hard retrieval questions (15), contradiction/alibi set (43).
- Code: retrieval store (SQLite FTS5 + sqlite-vec, hybrid RRF), 20 tests green.

In progress
- symbolic rules module (R1-R3) with 45 deterministic mini-graph tests.
- extraction pilot tail, then chunk-level embedding comparison, then answer-model check.

Risks
- Relations/claims extraction is weak on small models (F1 0.2-0.5 depending on metric); schema may need simplification.
- Gold sets were written by a Claude agent; human spot-check needed (see eval/*/README.md).
- Only 4 genuine R1 and 3 R2 cases exist in the corpus; R3 dominates.
- Benchmarks must run alone; timings taken under load are marked as such.

Decisions needed from the customer: none pending (carte blanche given for the night).
