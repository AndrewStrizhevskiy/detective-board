#!/usr/bin/env bash
# Progress of the running shards: counts per shard, chunks per minute, ETA, last log lines.
# Usage: scripts/server_progress.sh [--watch]   (--watch refreshes every 30 s)
set -u
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
D=data/cache/server
show() {
  uv run python scripts/server_report.py progress --dir "$D" || return 0
  local f
  for f in "$D"/logs/shard*.log; do
    [ -f "$f" ] || continue
    echo "-- $(basename "$f"):"
    tail -n 2 "$f" | sed 's/^/   /'
  done
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader | sed 's/^/GPU: /'
  command -v ollama >/dev/null 2>&1 && ollama ps 2>/dev/null | sed 's/^/   /'
}
if [ "${1:-}" = "--watch" ]; then
  while :; do clear; show; sleep 30; done
else
  show
fi
