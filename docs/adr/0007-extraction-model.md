# ADR-0007: Extraction model

- Status: **Proposed**
- Date: 2026-10-23
- Deciders: tech-lead
- Provisional parts: the whole choice rests on a 12-chunk pilot with gold generated automatically and not reviewed by a human. Revisit after a human spot-check of the gold set (`eval/extraction_gold/README.md`). Evidence: `docs/spike/REPORT.md` sections 6 and 7.

## Context

An LLM turns each chunk into entities, events, claims and relations, each with a verbatim quote (`src/detective_board/extract/schema.py`). The graph and the symbolic rules R1-R3 (ADR-0004) depend on claims and relations. Constraints: at most 8B parameters, CPU only, offline; extraction can run offline in the background, but the show date is 2026-10-30 and the freeze 2026-10-28/29.

## Options (12 chunks, `extract-*.jsonl`, scorers `score_extraction.py` and `overlap_metric.py`)

| Model | valid JSON | quotes verbatim | strict F1 ent / claim / rel | overlap F1 claim / rel / event | s per chunk | 596 chunks |
|---|---|---|---|---|---|---|
| qwen3:4b | 12/12 | 0.934 | 0.55 / 0.31 / 0.18 | 0.48 / 0.45 / 0.46 | 179.7 | 29.7 h |
| qwen3:4b-instruct | 11/12 | 0.908 | 0.58 / 0.28 / 0.24 | 0.50 / 0.35 / 0.44 | 235.3 | 39.0 h |
| qwen3:8b | 12/12 | 0.896 | 0.68 / 0.26 / 0.12 | 0.43 / 0.33 / 0.49 | 332.0 | 55.0 h |
| qwen2.5:7b | 12/12 | 0.841 | 0.60 / 0.30 / 0.10 | 0.40 / 0.33 / 0.43 | 283.4 | 46.9 h |
| gemma3:4b | 12/12 | 0.794 | 0.61 / 0.16 / 0.20 | 0.30 / 0.32 / 0.40 | 185.0 | 30.6 h |
| phi4-mini | 12/12 | 0.871 | 0.63 / 0.10 / 0.09 | 0.33 / 0.37 / 0.39 | 174.4 | 28.9 h |

Hours are derived (s per chunk x 596). qwen3:4b-instruct had one output cut at the 1536-token cap.

## Decision (proposed)

Extraction model: **qwen3:4b** with thinking off, constrained JSON-schema decoding, temperature 0, seed 42. Together with ADR-0006 this gives the pair bge-m3 + qwen3:4b. Reasons: best strict claim F1 (0.31), best relation overlap F1 (0.45), highest share of verbatim quotes (0.934), no invalid output, and the fastest tier (179.7 s per chunk). qwen3:8b has the best strict entity F1 (0.68) but costs 332 s per chunk (55 h) and scores lower on claims and relations.

Conditions and limits:
- Differences between the top four on claims (0.26-0.31 strict) are within noise at 12 chunks; the decision is "qwen3:4b is not worse and is cheaper", not "qwen3:4b is best". Confidence medium-low.
- Quotes that are not verbatim substrings (7-21 percent depending on model) must be re-anchored or dropped by `extract/ground.py` before entering the graph.
- Whole-corpus extraction is about 30 hours of exclusive machine time. Scope (full corpus or demo stories only, about 1.5 h per story) is a customer decision; reducing the schema size (fewer items, no entity quotes) should reduce time but is unmeasured.
- Reverse the decision if a human-reviewed gold set shows a different ranking, or if a smaller schema makes 8B affordable and clearly better on claims.

## Consequences

- Claims and relations stay weak (strict F1 around 0.2-0.3); derived findings must carry source quotes and the `conditional` mark (PRD section 6).
- Extraction results are cached per chunk and input hash (ingest is idempotent); a model change means re-extraction.
- The extraction model and the answer model (ADR-0008) can be the same runner, which avoids model swaps during a demo.
