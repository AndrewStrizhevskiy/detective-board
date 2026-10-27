#!/usr/bin/env bash
# The whole extraction session after scripts/server_bootstrap.sh. Resumable: finished phases are
# skipped (marker files in data/cache/server/state/), shards continue from their caches.
#
# Usage: scripts/server_run_all.sh [--phase LIST] [--streams N] [--parallel P] [--skip-gold12]
#                                  [--probe-story S] [--force] [--no-wait] [--allow-partial] [--dry-run]
#   --phase LIST     comma list of: determinism,probe,gold12,run,finish  (default: all of them in order)
#   --streams N      number of shard processes; skips the probe
#   --parallel P     OLLAMA_NUM_PARALLEL the server was started with (default: from bootstrap.env)
#   --skip-gold12    skip the 12-chunk quality check (30-60 min)
#   --probe-story S  story for the concurrency probe (default: first priority story NOT in the partial cache)
#   --force          redo the selected phases even if marked done
#   --no-wait        start the shards and return (then run the same command later to finish)
#   --allow-partial  let `finish` build the graph from fewer than all chunks
#   --dry-run        print the phases and commands, run nothing
# Logs: data/cache/server/logs/. Run inside tmux (tmux new -s extract), but shards survive without it.
# Options of the extraction (temperature 0, seed 42, num_ctx 4096, num_predict 1536) are NOT overridden:
# they are part of the cache key. Model: qwen3:4b, prompt extract-2.1 (defaults of extract.run).
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"
export PATH="$HOME/.local/bin:$PATH"

MODEL=qwen3:4b
SLUG="$(printf '%s' "$MODEL" | tr -c 'A-Za-z0-9.\n' '_')"
PARTIAL=data/extraction/extract-cache-qwen3_4b-extract-2.1-partial.sqlite
DET_STORY=boscombe-valley-mystery
PHASES="determinism,probe,gold12,run,finish"
STREAMS=""; PARALLEL=""; SKIP_GOLD=0; PROBE_STORY=""; FORCE=0; NOWAIT=0; PARTIAL_OK=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --phase) PHASES="${2:?}"; shift 2 ;;
    --streams) STREAMS="${2:?}"; shift 2 ;;
    --parallel) PARALLEL="${2:?}"; shift 2 ;;
    --skip-gold12) SKIP_GOLD=1; shift ;;
    --probe-story) PROBE_STORY="${2:?}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --no-wait) NOWAIT=1; shift ;;
    --allow-partial) PARTIAL_OK=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done
for p in $(echo "$PHASES" | tr ',' ' '); do
  case "$p" in determinism|probe|gold12|run|finish) ;; *) echo "unknown phase: $p" >&2; exit 2 ;; esac
done
want() { case ",$PHASES," in *",$1,"*) return 0 ;; esac; return 1; }

D=data/cache/server
mkdir -p "$D/logs" "$D/pids" "$D/state"
R() { uv run python scripts/server_report.py "$@"; }
say() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "ABORT: $*" >&2; exit 1; }
# run CMD..., log to file; in --dry-run only print
runlog() { local log="$1"; shift; echo "+ $* > $log"; [ "$DRY" -eq 1 ] && return 0; "$@" >"$log" 2>&1; }
done_p() { [ "$FORCE" -eq 0 ] && [ -f "$D/state/$1.done" ]; }
mark() { [ "$DRY" -eq 1 ] || date +%s >"$D/state/$1.done"; }
now() { date +%s.%N; }

if [ -z "$PARALLEL" ] && [ -f "$D/bootstrap.env" ]; then
  PARALLEL="$(sed -n 's/^OLLAMA_NUM_PARALLEL=//p' "$D/bootstrap.env")"
fi
[ -n "$PARALLEL" ] || die "do not know the server's OLLAMA_NUM_PARALLEL: run scripts/server_bootstrap.sh first or pass --parallel P"
if [ "$DRY" -eq 0 ]; then
  [ -f "$D/bootstrap.env" ] && grep -q '^BOOTSTRAP_OK=1' "$D/bootstrap.env" || echo "WARNING: bootstrap did not finish with PASS (or was not run): run scripts/server_bootstrap.sh first" >&2
  curl -fsS -m 3 http://localhost:11434/api/version >/dev/null || die "no Ollama server at localhost:11434 (run scripts/server_bootstrap.sh)"
fi
say "server parallel=$PARALLEL phases=$PHASES model=$MODEL"

# ------------------------------------------------------------ (a) determinism
phase_determinism() {
  if done_p determinism; then say "determinism: done already (use --force)"; return 0; fi
  say "== (a) determinism: 3 chunks of $DET_STORY vs the laptop partial cache"
  [ -f "$PARTIAL" ] || die "$PARTIAL missing in this checkout"
  local dir="$D/determinism"; rm -rf "$dir"; mkdir -p "$dir"
  local t0 t1; t0="$(now)"
  runlog "$dir/run.log" uv run python -m detective_board.extract.run --model "$MODEL" \
    --chunks data/chunks.jsonl --story "$DET_STORY" --limit 3 --cache "$dir/fresh.sqlite" \
    --out "$dir/out.jsonl" || die "extraction of the 3 chunks failed, see $dir/run.log"
  t1="$(now)"
  [ "$DRY" -eq 1 ] && return 0
  # SQLite creates -wal/-shm files even for reads: work on temp copies, never on the repo file
  local tmp; tmp="$(mktemp -d)"
  cp "$PARTIAL" "$tmp/laptop.sqlite"
  cp "$dir/fresh.sqlite" "$tmp/server.sqlite"; [ -f "$dir/fresh.sqlite-wal" ] && cp "$dir/fresh.sqlite-wal" "$tmp/server.sqlite-wal"
  local out
  out="$(uv run python scripts/merge_extract_cache.py verify "$tmp/laptop.sqlite" "$tmp/server.sqlite" \
    --model "$MODEL" --story "$DET_STORY" -n 3)"; local rc=$?
  rm -rf "$tmp"
  echo "$out" | tee "$dir/verify.txt"
  local compared identical different spc
  compared="$(echo "$out" | sed -n 's/.*compared=\([0-9]*\).*/\1/p')"
  identical="$(echo "$out" | sed -n 's/.*identical=\([0-9]*\).*/\1/p')"
  different="$(echo "$out" | sed -n 's/.*different=\([0-9]*\).*/\1/p')"
  spc="$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f",(b-a)/3}')"
  R kv "$D/determinism.json" "compared=${compared:-0}" "identical=${identical:-0}" "different=${different:-0}" "sec_per_chunk=$spc"
  if [ "${compared:-0}" -eq 0 ]; then die "determinism: nothing could be compared (see $dir/verify.txt)"; fi
  if [ "$rc" -ne 0 ]; then
    echo "WARNING: ${different} of ${compared} outputs differ from the laptop. Acceptable if equivalent in meaning (different float kernels); write the count in the report. Check 'ollama --version' and the model IDs if they differ strongly. Continuing."
  else
    say "determinism OK: $identical/$compared byte-identical, ${spc}s per chunk"
  fi
  mark determinism
}

# ------------------------------------------------------------ (b) concurrency probe
phase_probe() {
  if [ -n "$STREAMS" ]; then say "probe: skipped, --streams $STREAMS given"; return 0; fi
  if done_p probe && [ -f "$D/probe.json" ]; then say "probe: done already (use --force)"; return 0; fi
  say "== (b) concurrency probe (server OLLAMA_NUM_PARALLEL=$PARALLEL)"
  local story="$PROBE_STORY"
  if [ -z "$story" ]; then
    story="$(R pick-probe-story --cache "$PARTIAL" --model "$MODEL")" || die "no probe story"
  fi
  local ks=() k
  for k in 1 2 4; do [ "$k" -le "$PARALLEL" ] && ks+=("$k"); done
  say "probe story: $story; stream counts: ${ks[*]}"
  if [ "$DRY" -eq 1 ]; then echo "+ warm-up request, then for each k: split 8 chunks into k parts, run k extract.run in parallel, fresh cache each"; return 0; fi
  curl -fsS -m 300 http://localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false,\"think\":false,\"options\":{\"num_predict\":1}}" >/dev/null || die "warm-up request failed"
  local pairs=() n=8
  for k in "${ks[@]}"; do
    local dir="$D/probe/k$k"; rm -rf "$dir"; mkdir -p "$dir"
    n="$(R probe-split --story "$story" --n 8 --streams "$k" --outdir "$dir")"
    local t0 t1 pids=() i
    t0="$(now)"
    for ((i = 0; i < k; i++)); do
      uv run python -m detective_board.extract.run --model "$MODEL" --chunks "$dir/part$i.jsonl" \
        --cache "$dir/cache$i.sqlite" --out "$dir/out$i.jsonl" >"$dir/rep$i.json" 2>"$dir/log$i.txt" &
      pids+=("$!")
    done
    local bad=0; for p in "${pids[@]}"; do wait "$p" || bad=1; done
    t1="$(now)"
    [ "$bad" -eq 0 ] || die "probe with $k streams failed, see $dir/log*.txt"
    local spc; spc="$(awk -v a="$t0" -v b="$t1" -v n="$n" 'BEGIN{printf "%.2f",(b-a)/n}')"
    say "k=$k: $n chunks in $(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.0f",b-a}')s = ${spc}s per chunk"
    pairs+=("$k=$spc")
  done
  local best; best="$(R pick-streams "${pairs[@]}")"
  echo; echo "streams | seconds per chunk (wall clock / chunks)"
  for pr in "${pairs[@]}"; do echo "   ${pr%%=*}    | ${pr#*=}$([ "${pr%%=*}" = "$best" ] && echo '   <== best')"; done; echo
  local json="{" first=1
  for pr in "${pairs[@]}"; do [ $first -eq 1 ] || json+=","; first=0; json+="\"${pr%%=*}\":${pr#*=}"; done; json+="}"
  R kv "$D/probe.json" "story=\"$story\"" "chunks=$n" "results=$json" "best=$best" "server_parallel=$PARALLEL"
  mark probe
}

# ------------------------------------------------------------ (c) gold12
phase_gold12() {
  if [ "$SKIP_GOLD" -eq 1 ]; then say "gold12: skipped (--skip-gold12)"; return 0; fi
  if done_p gold12; then say "gold12: done already (use --force)"; return 0; fi
  say "== (c) gold12 quality check (qwen3:4b vs qwen3:8b with prompt v2.1; qwen3:8b must be pulled: bootstrap --with-8b; 15-40 min on a GPU)"
  if [ "$DRY" -eq 1 ]; then echo "+ scripts/server_gold12.sh --models \"qwen3:4b qwen3:8b\" --prompts prompts/extract/extract_v2_1.txt > $D/logs/gold12.log"; return 0; fi
  scripts/server_gold12.sh --models "qwen3:4b qwen3:8b" --prompts prompts/extract/extract_v2_1.txt >"$D/logs/gold12.log" 2>&1 || die "gold12 failed, see $D/logs/gold12.log (re-run to resume, or --skip-gold12)"
  tail -n 25 "$D/logs/gold12.log"
  mark gold12
}

# ------------------------------------------------------------ (d) full run
shard_done() { grep -q 'SHARD [0-9]* DONE (failures: 0)' "$D/logs/shard$1.log" 2>/dev/null; }
shard_alive() { local f="$D/pids/shard$1.pid"; [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; }

phase_run() {
  local n="$STREAMS"
  if [ -z "$n" ] && [ -f "$D/probe.json" ]; then n="$(sed -n 's/.*"best": *\([0-9]*\).*/\1/p' "$D/probe.json")"; fi
  if [ -z "$n" ] && [ -f "$D/run.json" ]; then n="$(sed -n 's/.*"streams": *\([0-9]*\).*/\1/p' "$D/run.json")"; fi
  [ -n "$n" ] || n=1
  if [ "$n" -gt "$PARALLEL" ]; then
    echo "WARNING: $n streams > server OLLAMA_NUM_PARALLEL=$PARALLEL; requests would queue. Using $PARALLEL."
    n="$PARALLEL"
  fi
  if [ -f "$D/run.json" ] && [ "$DRY" -eq 0 ]; then
    local old; old="$(sed -n 's/.*"streams": *\([0-9]*\).*/\1/p' "$D/run.json")"
    if [ -n "$old" ] && [ "$old" != "$n" ]; then
      [ "$FORCE" -eq 1 ] || die "a run with $old shards exists in $D; resume it with --streams $old (a different shard layout would repeat work), or --force to change"
      shard_alive 0 && die "shards are still running"
    fi
  fi
  say "== (d) full run: $n shard process(es), model $MODEL"
  uv run python scripts/extract_shards.py plan "$n" | grep '^shard'
  if [ "$DRY" -eq 1 ]; then echo "+ for k in 0..$((n - 1)): setsid nohup scripts/extract_shard.sh k $n $MODEL > $D/logs/shardk.log; pid -> $D/pids/shardk.pid"; return 0; fi
  if [ ! -f "$D/run.json" ] || [ "$(sed -n 's/.*"streams": *\([0-9]*\).*/\1/p' "$D/run.json")" != "$n" ]; then
    local base; base="$(R baseline --model "$MODEL")"
    R kv "$D/run.json" "streams=$n" "started=$(date +%s)" "baseline=$base"
  fi
  local k started=0
  for ((k = 0; k < n; k++)); do
    if shard_alive "$k"; then say "shard $k already running (pid $(cat "$D/pids/shard$k.pid"))"; continue; fi
    if shard_done "$k"; then say "shard $k finished already"; continue; fi
    setsid nohup scripts/extract_shard.sh "$k" "$n" "$MODEL" >>"$D/logs/shard$k.log" 2>&1 &
    echo $! >"$D/pids/shard$k.pid"
    started=$((started + 1))
    say "started shard $k/$n pid $!"
  done
  [ "$started" -gt 0 ] && R kv "$D/run.json" "last_launch=$(date +%s)"
  echo "progress any time: scripts/server_progress.sh"
  if [ "$NOWAIT" -eq 1 ]; then say "--no-wait: shards run in the background; run this script again to continue with 'finish'"; return 10; fi
  while :; do
    local alive=0; for ((k = 0; k < n; k++)); do shard_alive "$k" && alive=$((alive + 1)); done
    scripts/server_progress.sh | tail -n 1
    [ "$alive" -eq 0 ] && break
    sleep 60
  done
  local failed=0
  for ((k = 0; k < n; k++)); do shard_done "$k" || { echo "shard $k did not finish cleanly (see $D/logs/shard$k.log); run this script again to resume"; failed=1; }; done
  [ "$failed" -eq 0 ] || exit 1
  R kv "$D/run.json" "finished=$(date +%s)"
  mark run
}

# ------------------------------------------------------------ (e) finish
phase_finish() {
  say "== (e) finish: merge, graph, normalise, report"
  local k; for k in 0 1 2 3 4 5 6 7; do shard_alive "$k" && die "shard $k is still running; wait for it (scripts/server_progress.sh)"; done
  local srcs=(data/cache/extract-cache-"$SLUG"-shard*.sqlite)
  if [ "$DRY" -eq 1 ]; then
    echo "+ merge shard caches -> data/cache/extract-cache.sqlite (dry-run first), count, graph (run_extraction_priority.sh $MODEL 20), normalise, server_report.py report"; return 0
  fi
  [ -f "${srcs[0]}" ] || die "no shard caches found in data/cache/"
  uv run python scripts/merge_extract_cache.py merge data/cache/extract-cache.sqlite "${srcs[@]}" --model "$MODEL" --dry-run 2>&1 | tee "$D/logs/merge-dry.txt"
  local mrc
  uv run python scripts/merge_extract_cache.py merge data/cache/extract-cache.sqlite "${srcs[@]}" --model "$MODEL" >"$D/logs/merge.txt" 2>&1
  mrc=$?
  cat "$D/logs/merge.txt"
  [ "$mrc" -eq 0 ] || die "merge refused or had conflicts (see above); do NOT use --force without telling the lead"
  local total expected
  total="$(uv run python scripts/merge_extract_cache.py count data/cache/extract-cache.sqlite | sed 's/.*: //')"
  expected="$(wc -l < data/chunks.jsonl)"
  echo "merged entries: $total / expected chunks: $expected"
  if [ "$total" -lt "$expected" ] && [ "$PARTIAL_OK" -eq 0 ]; then
    die "only $total of $expected chunks are in the merged cache: run this script again to resume the shards, or --allow-partial"
  fi
  mkdir -p data/graph
  # the same three steps as `just graph` (all cache hits, no model calls when the cache is complete)
  scripts/run_extraction_priority.sh "$MODEL" 20 >"$D/logs/graph.log" 2>&1 || die "graph build failed, see $D/logs/graph.log"
  uv run python -m detective_board.extract.normalise data/graph/graph.sqlite | tee "$D/logs/normalise.log"
  R report --dir "$D" --out "$D/report.md"
  echo
  echo "TO COPY BACK:  data/cache/extract-cache.sqlite  data/graph/graph.sqlite  $D/report.md  (and $D/logs/)"
  mark finish
}

rc=0
want determinism && phase_determinism
want probe && phase_probe
want gold12 && phase_gold12
if want run; then phase_run; rc=$?; fi
if [ "$rc" -eq 10 ]; then exit 0; fi
want finish && phase_finish
say "ALL REQUESTED PHASES DONE"
