# ADR-0008: Answer model

- Status: **Accepted** (2026-10-23): qwen3:4b-instruct for answers, based on docs/spike/REPORT.md section 9 (n=12, medium-low confidence; revisit if retrieval or the prompt change materially).
- Date: 2026-10-23
- Deciders: tech-lead
- Provisional parts: the choice itself. No answer-quality number exists yet. The check writes `docs/spike/results/answers-20261023-082109.md` and `docs/spike/results/answers-20261023-082109-<model>.jsonl`; both were absent when this ADR was written.

## Context

The answer model reads retrieved chunks (and later graph facts and rule results) and writes a short answer with quotes, or refuses. Speed matters because the demo is live: only speed and memory are measured so far (`llm-20261022-17*.md`, 300-word prompt):

| Model | gen tok/s | TTFT s | peak RSS MiB |
|---|---|---|---|
| gemma3:4b | 7.73 | 15.30 | 4127 |
| phi4-mini | 7.73 | 17.09 | 3336 |
| qwen3:4b | 7.07 | 17.19 | 3526 |
| qwen3:4b-instruct | 7.04 | 19.46 | 3195 |
| qwen2.5:7b | 4.92 | 27.00 | 5029 |
| qwen3:8b | 4.34 | 29.49 | 6033 |

For a 150-token answer, qwen3:4b needs about 17 + 150/7.07 = 38 s and qwen3:8b about 29.5 + 150/4.34 = 64 s (derived; the 150 tokens are an assumption).

## Options

The candidates are the six models above. The check (`eval/run_answer_check.py`) runs the real Agent on the retrieval-only path, with the best retrieval configuration of ADR-0006, on 12 golden questions, one model at a time, plus a no-retrieval baseline for the best model. Its metrics are mechanical proxies (composite score, key-fact coverage), so they need a human read of a sample.

## Decision (proposed, provisional)

Pair recommendation: embeddings **bge-m3** (ADR-0006, Accepted) and extraction **qwen3:4b** (ADR-0007, Proposed). The answer model is provisionally **qwen3:4b** as well: same runner as extraction, no model swap, 7.07 tok/s, 17.2 s TTFT, 3.5 GiB. qwen3:8b is chosen instead only if the check shows a clear quality gain that is worth about 1.7x latency (29.5 vs 17.2 s TTFT, 4.34 vs 7.07 tok/s).

This ADR is not to be marked Accepted until:
1. the check files named above exist and their numbers are copied into REPORT section 9 and here;
2. the decision rule is applied to them: quality gain for 8B versus the latency cost, citation validity, and refusal behaviour;
3. a human has read a sample of the answers.

## Consequences

- Until then, demo timings and prompts are designed for the 4B budget (few LLM calls per question, short prompts and outputs, streamed progress, cached demo questions).
- If an 8B model wins, the answer step becomes the slowest part of every question and the demo relies more heavily on caching.
