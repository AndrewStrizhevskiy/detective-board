#!/usr/bin/env bash
# Targeted PRESENCE pass (src/detective_board/extract/presence.py, docs/symbolic-layer.md 11.3) on
# the GPU server, after scripts/server_run_all.sh has built data/graph/graph.sqlite.
# One run per model, each with its own cache, graph copy and predictions file; then presence_eval.
# Resumable (the cache key holds model, prompt version and schema version): run it again after an
# interruption. Quality is UNMEASURED until this has run: read data/cache/server/presence/eval.json.
#
# Usage: scripts/server_presence.sh [--models "qwen3:8b qwen3:4b-instruct"] [--all] [--limit N]
#                                   [--lenient] [--pull] [--dry-run]
#   --models LIST  Ollama tags, space separated (default: qwen3:8b qwen3:4b-instruct)
#   --all          after the demo stories, run every story (demo chunks are cache hits)
#   --limit N      only the first N chunks of each selected set (smoke test)
#   --lenient      keep values not found in the quote as LOW context (A/B against strict; own cache
#                  is shared, grounding is not cached, so the model is NOT called again)
#   --pull         `ollama pull` a model that the server does not list
#   --dry-run      print the commands, run nothing
# Output: data/cache/server/presence/<model>.jsonl (+ -lenient), eval.json; caches data/cache/presence-cache-<model>.sqlite;
#         graphs data/graph/presence-<model>.sqlite (copies of graph.sqlite + the presence facts).
set -u
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

MODELS="qwen3:8b qwen3:4b-instruct"
DEMO="wisteria-lodge boscombe-valley-mystery silver-blaze thor-bridge abbey-grange"
ALL=0; LIMIT=0; LENIENT=0; PULL=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --models) MODELS="${2:?}"; shift 2 ;;
    --all) ALL=1; shift ;;
    --limit) LIMIT="${2:?}"; shift 2 ;;
    --lenient) LENIENT=1; shift ;;
    --pull) PULL=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done

OUT=data/cache/server/presence
GRAPH=data/graph/graph.sqlite
mkdir -p "$OUT" data/graph data/cache
say() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "ABORT: $*" >&2; exit 1; }
run() { echo "+ $*"; [ "$DRY" -eq 1 ] || "$@"; }
# runlog LOG REPORT CMD...: stderr to LOG, stdout (the JSON report) to REPORT
runlog() { local log="$1" rep="$2"; shift 2; echo "+ $* 2>$log >$rep"; [ "$DRY" -eq 1 ] || "$@" 2>"$log" >"$rep"; }
slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9.\n' '_'; }

if [ "$DRY" -eq 0 ]; then
  curl -fsS -m 3 http://localhost:11434/api/version >/dev/null || die "no Ollama server at localhost:11434 (scripts/server_bootstrap.sh)"
  [ -f "$GRAPH" ] || die "$GRAPH missing: run scripts/server_run_all.sh first (the pass needs the story's known people and places)"
fi

stories=(); for s in $DEMO; do stories+=(--story "$s"); done
extra=(); SUF=""
[ "$LIMIT" -gt 0 ] && extra+=(--limit "$LIMIT")
[ "$LENIENT" -eq 1 ] && { extra+=(--lenient); SUF="-lenient"; }

preds=()
for model in $MODELS; do
  m="$(slug "$model")"
  say "== model $model"
  if [ "$DRY" -eq 0 ] && ! curl -fsS -m 10 http://localhost:11434/api/tags | grep -q "\"$model\""; then
    if [ "$PULL" -eq 1 ]; then run ollama pull "$model" || die "pull of $model failed"
    else die "$model is not on the server: ollama pull $model (or --pull)"; fi
  fi
  g="data/graph/presence-$m$SUF.sqlite"
  [ -f "$g" ] || run cp "$GRAPH" "$g"
  cache="data/cache/presence-cache-$m.sqlite"
  say "demo stories: $DEMO"
  runlog "$OUT/$m$SUF.log" "$OUT/$m$SUF.report.json" \
    uv run python -m detective_board.extract.presence --model "$model" --chunks data/chunks.jsonl \
    "${stories[@]}" "${extra[@]}" --cache "$cache" --graph-db "$g" --out "$OUT/$m$SUF.jsonl" \
    || die "presence run failed, see $OUT/$m$SUF.log (run again to resume)"
  if [ "$ALL" -eq 1 ]; then
    say "all stories"
    runlog "$OUT/$m-all$SUF.log" "$OUT/$m-all$SUF.report.json" \
      uv run python -m detective_board.extract.presence --model "$model" --chunks data/chunks.jsonl \
      "${extra[@]}" --cache "$cache" --graph-db "$g" --out "$OUT/$m-all$SUF.jsonl" \
      || die "presence run (all) failed, see $OUT/$m-all$SUF.log"
    preds+=("$OUT/$m-all$SUF.jsonl")
  else
    preds+=("$OUT/$m$SUF.jsonl")
  fi
  [ "$DRY" -eq 1 ] || { echo "-- $model report:"; cat "${preds[-1]%.jsonl}.report.json"; }
done

say "== evaluation (no model): gold from eval/extraction_gold and eval/golden/contradictions.jsonl"
run uv run python scripts/spike/presence_eval.py "${preds[@]}" --json "$OUT/eval$SUF.json" --gold-out "$OUT/gold.jsonl"
[ "$DRY" -eq 1 ] || echo "scores: $OUT/eval$SUF.json   TO COPY BACK: $OUT/ data/cache/presence-cache-*.sqlite data/graph/presence-*.sqlite"
say "DONE"
