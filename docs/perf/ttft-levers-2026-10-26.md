# Time-to-first-token levers (2026-10-26, target laptop, Ollama 0.35.0, CPU only)

Model qwen3:4b-instruct (think off), real answer prompt for g001 (system 694 chars + sources/question 3273
chars = 1080 tokens), num_predict 1 so the wall time is the prefill. One run per variant (so differences of
a few percent are noise), laptop otherwise idle (only docs agents without CPU use). Script: not committed
(ad-hoc); method: nonce at the start of the user message so only the system-prompt prefix can be reused.

| Variant | prefill time | uncached prompt tok/s |
|---|---|---|
| default, system prefix NOT cached (nonce in system prompt) | 52.7 s | 20.4 |
| default, system prefix cached (153 of 1080 tokens) | **42.7 s** | 21.7 |
| num_batch 1024 | 49.0 s | 22.1 |
| num_batch 2048 | 48.0 s | 22.5 |
| num_thread 4 | 48.3 s | 22.4 |
| num_thread 6 | 50.8 s | 21.3 |
| num_thread 8 | 48.2 s | 22.4 |
| num_ctx 2048 | 48.3 s | 22.4 |

Conclusions
- Prefill is compute-bound at about 21-22 tokens/s. Threads, batch size and num_ctx change nothing beyond noise.
- The only lever that helped is prefix reuse of the static system prompt: about 8-10 s. It needs the model to be
  resident and warm (a warm-up request at start-up, a long `keep_alive`).
- Every 100 prompt tokens cost about 4.5 s. Going from 1080 to about 700 tokens would save about 17 s, at the
  price of evidence coverage (see docs/spike/results/evidence-20261023-093201.md).
- Plan for 43-50 s to first token on stage and fill the wait with trace events and evidence cards.
- Not measured: flash attention and KV-cache quantisation (server-side environment settings; unlikely to matter
  for a compute-bound CPU prefill), other quantisations of the model.
