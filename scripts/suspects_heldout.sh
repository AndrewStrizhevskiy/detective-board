#!/usr/bin/env bash
# One run of the frozen held-out confirmation (docs/spike/results/suspects-prereg-heldout-20261030.md).
# extraction of the pre-cut chunks -> graph -> pairwise_14b + fulltext_14b + bare -> score. One GPU job at a time.
#   setsid nohup scripts/suspects_heldout.sh > data/cache/suspects/heldout/driver.log 2>&1 < /dev/null &
set -u
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
OUT=data/cache/suspects/heldout
mkdir -p "$OUT/cache"
G=data/graph/heldout.sqlite
LOCK=/tmp/db-llm.lock
RUN="uv run python eval/suspects_run.py"
COLLECT="$RUN collect --cases eval/suspects/heldout_cases.jsonl --clean-dir data/heldout/clean --chunks-file data/heldout/chunks.jsonl --graph $G --variants open --num-ctx 14336 --cache-dir $OUT/cache"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/driver.log.txt"; }

for slug in fb-hammer-of-god fb-invisible-man fb-secret-garden fb-eye-of-apollo fb-three-tools fb-wrong-shape; do
  log "extract $slug"
  flock -w 3600 "$LOCK" uv run python -m detective_board.extract.run --model qwen3:4b \
    --prompt prompts/extract/extract_v2_1.txt --chunks data/heldout/chunks.jsonl --story "$slug" \
    --cache data/cache/heldout-extract-cache.sqlite --out "$OUT/extract-$slug.jsonl" --graph-db "$G" \
    >> "$OUT/extract.log" 2>&1 || log "extract $slug FAILED"
done
if [ ! -e "$OUT/main14b.done" ]; then
  log "collect qwen3:14b (pairwise + fulltext)"
  flock -w 3600 "$LOCK" $COLLECT --model qwen3:14b --suffix _14b --methods pairwise fulltext --out "$OUT/main14b.json" \
    > "$OUT/main14b.log" 2>&1 && touch "$OUT/main14b.done"
fi
if [ ! -e "$OUT/bare8b.done" ]; then
  log "collect qwen3:8b (bare)"
  flock -w 3600 "$LOCK" $COLLECT --model qwen3:8b --methods bare --out "$OUT/bare8b.json" \
    > "$OUT/bare8b.log" 2>&1 && touch "$OUT/bare8b.done"
fi
$RUN score "$OUT/main14b.json" "$OUT/bare8b.json" --only-split all --label HELDOUT \
  --report "$OUT/HELDOUT.score.json" --md "$OUT/HELDOUT.md" --summary "$OUT/SUMMARY.txt" > "$OUT/score.log" 2>&1
log "done"
echo "finished $(date '+%F %T')" > "$OUT/DONE.txt"
