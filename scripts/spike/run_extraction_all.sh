#!/usr/bin/env bash
# Runs the extraction pilot for all candidate models, one process per model, 45 s cooldown between.
set -u
cd "$(dirname "$0")/../.."
for m in "$@"; do
  uv run --with pydantic python scripts/spike/run_extraction.py "$m" || echo "FAILED $m"
  sleep 45
done
echo ALLDONE
