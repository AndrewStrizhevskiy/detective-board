#!/usr/bin/env bash
# Score the production extractor on the 12 gold chunks for every model x prompt, then print one
# comparison table and write docs/spike/results/gold12-<stamp>.md. Needs a running Ollama with the
# models pulled. Resumable: per-run caches make finished chunks free, and a run whose output already
# has 12 lines is skipped (FORCE=1 reruns it, still through the cache).
#
# Usage:  scripts/server_gold12.sh [--models "qwen3:4b qwen3:4b-instruct"] \
#             [--prompts "prompts/extract/extract_v2.txt prompts/extract/extract_v2_1.txt"]
# Env:    OLLAMA_HOST (default http://localhost:11434), EXTRA_ARGS (extra args for extract.run),
#         STAMP (default: date), FORCE=1.
# run.py defaults (temperature 0, seed 42, num_ctx 4096, num_predict 1536) are kept on purpose.
set -euo pipefail
cd "$(dirname "$0")/.."

MODELS="qwen3:4b qwen3:4b-instruct"
PROMPTS="prompts/extract/extract_v2.txt prompts/extract/extract_v2_1.txt"
while [ $# -gt 0 ]; do
  case "$1" in
    --models) MODELS="$2"; shift 2 ;;
    --prompts) PROMPTS="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done
STAMP="${STAMP:-$(date +%Y%m%d-%H%M%S)}"
HOST="${OLLAMA_HOST:-http://localhost:11434}"
case "$HOST" in http*) ;; *) HOST="http://$HOST" ;; esac
DIR=data/cache/gold12
mkdir -p "$DIR"

run() { echo "+ $*" >&2; "$@"; }

run uv run python scripts/server_gold12.py chunks --out data/cache/gold12.jsonl

OUTS=()
FAILED=()
for model in $MODELS; do
  for prompt in $PROMPTS; do
    slug="$(uv run python scripts/server_gold12.py slug "$model" "$prompt")"
    out="$DIR/$slug.jsonl"
    OUTS+=("$out")
    if [ -z "${FORCE:-}" ] && [ -f "$out" ] && [ "$(wc -l < "$out")" -ge 12 ]; then
      echo "== $slug: done already ($out), skipping (FORCE=1 to rerun)" >&2
      continue
    fi
    echo "== $slug $(date +%H:%M)" >&2
    # shellcheck disable=SC2086
    run uv run python -m detective_board.extract.run --model "$model" --prompt "$prompt" \
      --chunks data/cache/gold12.jsonl --cache "$DIR/$slug.sqlite" --out "$out" \
      --host "$HOST" ${EXTRA_ARGS:-} >"$DIR/$slug.report.json" || {
        echo "FAILED $slug (re-run the script to resume)" >&2
        FAILED+=("$slug")
      }
  done
done

echo "== scoring" >&2
EXISTING=()
for o in "${OUTS[@]}"; do [ -s "$o" ] && EXISTING+=("$o"); done
[ "${#EXISTING[@]}" -gt 0 ] || { echo "no outputs to score" >&2; exit 1; }
run uv run python scripts/server_gold12.py report --stamp "$STAMP" "${EXISTING[@]}"
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "incomplete runs: ${FAILED[*]}" >&2
  exit 1
fi
