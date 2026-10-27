# ADR-0012: Generic extraction prompt stays v2.1 plus deterministic repair

- Status: Accepted (2026-10-26, recorded 2026-10-27).
- Date: 2026-10-26
- Deciders: tech-lead
- Provisional parts: all numbers are from 12 gold chunks (AI-labelled) or from a 64-chunk cached sample; the repair "after" figures are from `scripts/eval/repair_eval.py` runs reported on 2026-10-26 and were not re-run for this ADR.

## Context

The generic extraction (qwen3:4b, prompt `extract-2.1`, ADR-0007) fills the graph, but the real raw output is not usable for the rules. Measured on cached Wisteria/Boscombe chunks (`docs/symbolic-layer.md` 11.2: 64 chunks, 177 events, 226 claims; the brief of 2026-10-27 states 178 events, so the event count differs by one between sources and is not reconciled): `participants` empty in every event (178/178 in the brief), `polarity=deny` in 222 of 226 claims (98%), `time_text` and `place` filled in all events and copied from the start of the chunk. R1/R3 found nothing on Wisteria Lodge (133 `DENIAL_NOT_MODELLED`, 0 events dated).

A v2.2 prompt with a worked example was tried (`docs/spike/results/prompt-v2-2-20261026.md`, 12 gold chunks, one run each, temperature 0, seed 42):

| metric | v2.1 | v2.2 first run (example without entities/relations) | v2.2 after the example fix |
|---|---|---|---|
| event participants non-empty | 0% | 33% | n/a (not in the gold12 table) |
| claim polarity=deny share | 91% | 12% | 12% |
| claims with a person / place / time filled | 91% / 77% / 89% | 21% / 16% / 9% | 6% / 0% / 0% |
| strict F1 entities | 0.557 | 0.000 | 0.506 |
| strict F1 claims | 0.200 | 0.283 | 0.200 |
| strict F1 relations | 0.136 | 0.026 | 0.060 |
| seconds per chunk | 233.7 | 170.5 | 152.0 |

Sources: `docs/spike/results/prompt-v2-2-20261026.md` and `gold12-v22.md` (v2.1 and the first v2.2 run), `gold12-20261026-210753.md` (v2.2 after the example was completed so that the model keeps entities and relations). The earlier STATUS figures (entities 0.51, relations 0.06) are the fixed run.

## Options

1. **Adopt v2.2.** Better polarity and participants, but entities and relations collapse and the time/place fields are mostly empty. Rejected.
2. **Keep v2.1 and fix the fields afterwards** with a deterministic repair step (`extract/repair.py`, `docs/symbolic-layer.md` 11.2): participants from persons mentioned in the item's own quote, polarity from negation cues in the quote, `in_speech` from quotation spans, time/place kept only if they appear in the item's own quote (otherwise moved to `*_inherited`, low, never exact), claim `about_*` fields kept only if grounded. Deterministic, idempotent, no LLM; model values are kept in audit fields; the cache key is unchanged so existing cache entries stay valid.
3. **Per-field extra model calls.** Too slow on the laptop (190-250 s per chunk already).

## Decision

Option 2. The generic prompt stays `extract-2.1`; v2.2 is not adopted. Reported effect of the repair on the 64-chunk sample (STATUS 2026-10-26): participants non-empty 0 -> 122 of 177 events, `deny` share 98% -> 16%, copied time/place demoted. The repair cannot create information the text does not have: on the first real run (wisteria-lodge, repaired) there were 107 events and 137 claims, 0 exact times, 0 days and 1 usable proposition, so R1/R3 still find nothing automatically. Rules get their input from the presence pass and curated facts (ADR-0011).

## Consequences

- Cache entries made with v2.1 on the laptop (231 chunks, 8 stories, `data/extraction/laptop-cache-qwen3_4b-extract-2.1.sqlite`) remain valid and seed the server run, so those chunks are cache hits there. Mixed CPU/GPU cache entries use the same keys; small numeric differences are possible.
- `GRAPH_BUILD_VERSION` is 3 after the repair (inherited values are low).
- The repair removes wrong values; it does not recall missing ones. Extraction quality on the full corpus is unmeasured; the server run will say how many events have exact times and days.
- Revisit if a prompt variant beats v2.1 on entities and relations (not only polarity) on the 12 gold chunks.
