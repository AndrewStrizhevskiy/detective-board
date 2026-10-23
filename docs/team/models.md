# Models (exact tags and digests)

Everyone must use the same tags. Digests below are from `ollama list` on the reference
laptop (2026-10-23). After `ollama pull`, compare the ID column with this table; a different
ID means a different build and cached outputs will not be comparable.

| Tag | Role | Digest (ID) | Size |
|---|---|---|---|
| `bge-m3:latest` | embeddings | `790764642607` | 1.2 GB |
| `qwen3:4b` | extraction (default shard model) | `359d7dd4bcda` | 2.5 GB |
| `qwen3:4b-instruct` | answer / agent candidate | `0edcdef34593` | 2.5 GB |
| `gemma3:4b` | extraction / answer comparison | `68ceab7e468a` | 3.4 GB |
| `qwen3:8b` | upper-bound comparison | `500a1f067a9f` | 5.2 GB |

Pull: `ollama pull bge-m3 && ollama pull qwen3:4b && ollama pull qwen3:4b-instruct && ollama pull gemma3:4b && ollama pull qwen3:8b`

Also present on the reference laptop (spike only, not needed): `qwen2.5:7b` (`845dbda0ea48`),
`phi4-mini` (`78fad5d182a7`), `snowflake-arctic-embed` (`21ab8b9b0545`), `all-minilm`
(`1b226e2802db`), `nomic-embed-text` (`0a109f422b47`), `translategemma:4b` (`c49d986b0764`).

Check: `ollama list` and compare IDs. The `ID` column is the 12-char prefix of the manifest digest.

## Cache key and what must match

The extraction cache key is `sha256(chunk text, model tag, prompt version, schema version,
options)`; options are temperature 0, seed 42, num_ctx 4096, num_predict 1536 (defaults of
`python -m detective_board.extract.run`). Do not change these for shard runs. Same GPU or not,
outputs can differ slightly across hardware and Ollama versions: record `ollama --version`
and the GPU in the PR (see Package A in `ASSIGNMENTS.md`).
