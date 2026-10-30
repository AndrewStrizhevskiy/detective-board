# R3 semantic, dev split (judge, R3J-2)

- 2026-10-29 00:08, git `44fd4c3`, model `qwen3:4b-instruct`, max pairs 12, person filter True, host mendax-ThinkPad-X1-Carbon-7th
- Dev split only (23 cases, tuned on dev: optimistic). A positive is found when a pair judged `contradicts` has BOTH quotes matching two different involved claims of the case (strict) or at least one (loose); matching = content-word coverage >= 0.6 of the shorter side. A control is a false positive when any pair among its judged pairs is judged `contradicts`. The model verdict is a hypothesis, not a rule verdict. Gold sets are generated automatically.

| measure | value |
|---|---|
| baseline recall on automatic facts (rules) | 0.00 [0.00, 0.22] (0/14) |
| candidate recall, strict (no model) | 0.07 [0.01, 0.31] (1/14) |
| candidate recall, loose (no model) | 0.50 [0.27, 0.73] (7/14) |
| recall matched to the case, strict | 0.07 [0.01, 0.31] (1/14) |
| recall matched to the case, loose | 0.36 [0.16, 0.61] (5/14) |
| controls with any `contradicts` (false positives) | 0.89 [0.56, 0.98] (8/9) |
| invalid model answers | 0 of 235 |
| pairs per case (mean) | 10.22 |
| seconds, all cases | 978.5 |

| case | kind | exp | pairs | cand s/l | contradicts | strict | loose | s |
|---|---|---|---|---|---|---|---|---|
| c001 | R1 | 1 | 12 | 0/1 | 0 | 0 | 0 | 101.31 |
| c004 | R1 | 1 | 12 | 0/1 | 7 | 0 | 1 | 48.43 |
| c006 | R2 | 1 | 2 | 0/0 | 2 | 0 | 0 | 7.09 |
| c007 | R2 | 1 | 12 | 1/1 | 6 | 1 | 1 | 52.8 |
| c009 | R3 | 1 | 12 | 0/0 | 6 | 0 | 0 | 50.06 |
| c010 | R3 | 1 | 12 | 0/0 | 6 | 0 | 0 | 47.09 |
| c012 | R3 | 1 | 12 | 0/1 | 6 | 0 | 1 | 47.21 |
| c013 | R3 | 1 | 12 | 0/0 | 2 | 0 | 0 | 48.45 |
| c014 | R3 | 1 | 5 | 0/1 | 0 | 0 | 0 | 18.57 |
| c018 | R3 | 1 | 12 | 0/1 | 3 | 0 | 1 | 44.03 |
| c020 | R3 | 1 | 3 | 0/0 | 0 | 0 | 0 | 11.43 |
| c021 | R3 | 1 | 8 | 0/1 | 2 | 0 | 1 | 29.01 |
| c022 | R3 | 1 | 1 | 0/0 | 1 | 0 | 0 | 5.01 |
| c025 | R3 | 1 | 12 | 0/0 | 4 | 0 | 0 | 50.91 |
| c028 | consistent | 0 | 12 | 0/0 | 4 | 0 | 0 | 44.48 |
| c031 | consistent | 0 | 12 | 0/0 | 1 | 0 | 0 | 46.93 |
| c033 | consistent | 0 | 12 | 0/0 | 5 | 0 | 0 | 47.12 |
| c034 | consistent | 0 | 12 | 0/1 | 3 | 0 | 0 | 45.94 |
| c035 | consistent | 0 | 12 | 0/0 | 3 | 0 | 0 | 46.37 |
| c036 | consistent | 0 | 12 | 0/0 | 2 | 0 | 0 | 40.26 |
| c039 | consistent | 0 | 12 | 0/0 | 0 | 0 | 0 | 49.32 |
| c040 | consistent | 0 | 12 | 0/0 | 6 | 0 | 0 | 42.28 |
| c041 | consistent | 0 | 12 | 1/1 | 6 | 1 | 1 | 54.37 |
