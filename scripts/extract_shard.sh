#!/usr/bin/env bash
# Run one shard of the extraction on this machine (e.g. a GPU box).
# Usage: scripts/extract_shard.sh <shard-id> <n-shards> [model]
#   shard-id in 0..n-1; model defaults to qwen3:4b (use the SAME tag everywhere, see docs/team/models.md).
# Writes a shard-specific cache: data/cache/extract-cache-<model-slug>-shard<k>.sqlite
# Resumable: finished chunks are cache hits. Extra args for run.py: set EXTRA_ARGS="--num-ctx 4096".
# Defaults of run.py (temperature 0, seed 42, num_ctx 4096, num_predict 1536) are NOT overridden
# on purpose: they are part of the cache key and must match the laptop run.
set -u
cd "$(dirname "$0")/.."
if [ $# -lt 2 ]; then
  echo "usage: $0 <shard-id> <n-shards> [model]" >&2
  exit 2
fi
K="$1"
N="$2"
MODEL="${3:-qwen3:4b}"
SLUG="$(printf '%s' "$MODEL" | tr -c 'A-Za-z0-9.\n' '_')"
CACHE="data/cache/extract-cache-${SLUG}-shard${K}.sqlite"
OUTDIR="data/cache/shard${K}-${SLUG}"
mkdir -p data/cache "$OUTDIR"
mapfile -t STORIES < <(uv run python scripts/extract_shards.py stories "$K" "$N") || exit 2
[ "${#STORIES[@]}" -gt 0 ] || { echo "empty shard $K/$N" >&2; exit 2; }
echo "shard $K/$N model=$MODEL cache=$CACHE stories=${STORIES[*]}"
fail=0
for s in "${STORIES[@]}"; do
  echo "== story $s $(date +%H:%M)"
  # shellcheck disable=SC2086
  uv run python -m detective_board.extract.run --model "$MODEL" --chunks data/chunks.jsonl \
    --story "$s" --cache "$CACHE" --out "$OUTDIR/extract-$s.jsonl" ${EXTRA_ARGS:-} || {
    echo "FAILED $s"
    fail=1
  }
done
echo "SHARD $K DONE (failures: $fail); cache entries:"
uv run python scripts/merge_extract_cache.py count "$CACHE"
exit "$fail"
