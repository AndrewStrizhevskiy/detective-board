# Server extraction report

## Environment

- commit: `1d631fd35cf6a48ad3134b8def2ea116c7acaef8`
- ollama: `ollama version is 0.40.11`
- GPU / VRAM / driver: NVIDIA GeForce RTX 4070, 12282 MiB, 580.105.08
- generated: 2026-10-27 19:09:54

## Model IDs (`ollama list`)

- `bge-m3:latest` 790764642607
- `qwen3:4b` 359d7dd4bcda
- `qwen3:4b-instruct` 0edcdef34593
- `qwen3:8b` 500a1f067a9f

## Seconds per chunk

| phase | seconds per chunk | note |
|---|---|---|
| determinism (3 chunks, 1 stream) | 6.5 | |
| probe, 1 stream(s) | 7.02 | wall clock / chunks |
| probe, 2 stream(s) | 4.35 | wall clock / chunks |
| probe, 4 stream(s) | 3.16 | wall clock / chunks (chosen) |
| full run, 4 streams, effective | n/a | wall clock / live chunks |
| full run, per request (mean) | n/a | |

## Determinism check against the laptop partial cache

- compared 3, byte-identical 0, different 3

## Corpus numbers

- total chunks: 596 (status {'ok': 596})
- items kept: 8663, dropped: 125
- dropped by reason: {'duplicate': 14, 'quote_not_grounded': 111}
- events with a time (time_text): 0.193; normalised time: 0.525; with story day: 0.045 (of 1693 events)
- claims with a proposition: 0.007 (of 2152)
- stories with zero events: [] (of 20)

## gold12 quality check

- qwen3_4b__extract_v2_1: sec_per_chunk_live 6.8, valid_json_rate 1.0, grounded_rate 0.983
- qwen3_8b__extract_v2_1: sec_per_chunk_live 11.3, valid_json_rate 1.0, grounded_rate 0.982
- full table: docs/spike/results/gold12-*.md

## Anything unusual

(write here)
