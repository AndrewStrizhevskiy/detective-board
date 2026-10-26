# Team docs

- `../../CONTRIBUTING.md`: setup, branches, commits, PR rules, zones, what not to commit, tests.
- `ASSIGNMENTS.md`: four work packages (A extraction on strong hardware, B UI polish and e2e, C eval and human review, D run/package/present) and the orchestrator's focus. Deadline 2026-10-27 18:00, freeze 2026-10-28.
- `models.md`: exact Ollama tags and digests; cache key parts that must match.

## Sharded extraction (Package A tools)

```bash
uv run python scripts/extract_shards.py plan 4                 # show the balanced split
scripts/extract_shard.sh <shard-id> <n-shards> [model]         # default model qwen3:4b
#   -> data/cache/extract-cache-<model-slug>-shard<k>.sqlite   (slug: qwen3:4b -> qwen3_4b)
uv run python scripts/merge_extract_cache.py merge data/cache/extract-cache.sqlite \
    data/cache/extract-cache-qwen3_4b-shard*.sqlite --model qwen3:4b [--dry-run] [--force]
uv run python scripts/merge_extract_cache.py verify CACHE_A.sqlite CACHE_B.sqlite --model qwen3:4b -n 3
uv run python scripts/merge_extract_cache.py count data/cache/*.sqlite
```

Shard planning reads the story order from `scripts/run_extraction_priority.sh` and balances by
chunk count. Merge recomputes the expected cache keys from `data/chunks.jsonl` + model + prompt
version + schema version + options and refuses entries outside that set unless `--force`.
It is idempotent and never overwrites existing entries. After merging, run
`just graph qwen3:4b 20` once (merges shard caches if you pass them as the third argument, runs
`scripts/run_extraction_priority.sh`, then `extract.normalise`): every chunk is a cache hit and it builds
`data/graph/graph.sqlite` without calling the model. `just normalise` re-runs only the last step. Tests: `tests/test_extract_shards.py`.
