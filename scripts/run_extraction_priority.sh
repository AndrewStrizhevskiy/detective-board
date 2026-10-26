#!/usr/bin/env bash
# Extract the graph story by story, most useful stories first (usage in golden/contradiction/demo sets).
# Resumable: results are cached by chunk hash+model+prompt, so re-running skips finished chunks.
# Usage: scripts/run_extraction_priority.sh [MODEL] [N_STORIES]
set -u
cd "$(dirname "$0")/.."
MODEL="${1:-qwen3:4b}"
N="${2:-10}"
STORIES=(${ORDER:-boscombe-valley-mystery silver-blaze black-peter blue-carbuncle reigate-squires \
  red-headed-league abbey-grange man-with-the-twisted-lip thor-bridge crooked-man \
  norwood-builder speckled-band naval-treaty priory-school scandal-in-bohemia \
  resident-patient beryl-coronet wisteria-lodge copper-beeches musgrave-ritual})
mkdir -p data/cache data/graph
for s in "${STORIES[@]:0:$N}"; do
  echo "== story $s $(date +%H:%M)"
  uv run python -m detective_board.extract.run --model "$MODEL" --prompt "${PROMPT:-prompts/extract/extract_v2_1.txt}" --chunks data/chunks.jsonl \
    --story "$s" --cache data/cache/extract-cache.sqlite --out "data/cache/extract-$s.jsonl" \
    --graph-db data/graph/graph.sqlite || echo "FAILED $s"
done
echo ALLDONE
