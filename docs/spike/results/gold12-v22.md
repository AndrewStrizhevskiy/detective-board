# Gold-12 comparison v22

Production pipeline (schema v2) on the 12 chunks of `eval/extraction_gold/`. Scorer: `scripts/spike/score_pipeline.py`. Runs: qwen3_4b__extract_v2_1, qwen3_4b__extract_v2_2.

| run | json ok | usable | grounded | s/chunk | ent P | R | F1 | cla P | R | F1 | rel P | R | F1 | ovl clm F1 | ovl rel F1 | person | place | time | deny | in_speech | transit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3_4b__extract_v2_1 | 100% | 100% | 100% | 233.7 | 0.830 | 0.419 | 0.557 | 0.227 | 0.179 | 0.200 | 0.133 | 0.140 | 0.136 | 0.36 | 0.44 | 91% | 77% | 89% | 91% | 41% | 32% |
| qwen3_4b__extract_v2_2 | 100% | 100% | 100% | 170.5 | 0.000 | 0.000 | 0.000 | 0.326 | 0.250 | 0.283 | 0.030 | 0.023 | 0.026 | 0.36 | 0.20 | 21% | 16% | 9% | 12% | 45% | 24% |

json ok = status ok; usable = ok or repaired; person/place/time/deny = share of claims; in_speech/transit = share of events. The gold sets are AI-labelled (not human-checked).
