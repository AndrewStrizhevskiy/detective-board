#!/usr/bin/env bash
# Overnight queue for the suspect board experiments (issue #21). One GPU job at a time, back to back,
# resumable (finished steps leave a .done marker, model answers are cached), stops at the deadline.
#
#   setsid nohup scripts/suspects_overnight.sh > data/cache/suspects/overnight/driver.log 2>&1 < /dev/null &
#
# Every step writes results/<NAME>.json (collect), <NAME>.score.json / <NAME>.md (score) and appends
# one line per method to SUMMARY.txt as soon as it finishes, so a cut at the deadline loses nothing.
# Discipline: the test split is spent (one run, frozen protocol); new variants run on dev only;
# no tuning here: all scoring uses the frozen defaults of docs/spike/results/suspects-prereg-*.md.
# Stop it: kill the PID in overnight/driver.pid, then kill the python processes that `ps` lists
# for eval/suspects_run.py (see README_MORNING.txt).
set -u
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

OUT=data/cache/suspects/overnight
SUSPECTS=data/cache/suspects
mkdir -p "$OUT/logs" "$OUT/results"
echo $$ > "$OUT/driver.pid"
DEADLINE_HHMM="${DEADLINE_HHMM:-07:00}"
now=$(date +%s)
DL=$(date -d "$DEADLINE_HHMM" +%s)
[ "$now" -ge "$DL" ] && DL=$(date -d "tomorrow $DEADLINE_HHMM" +%s)
RUN="uv run python eval/suspects_run.py"
BASE="$OUT/results/baselines.json"
LOCK=/tmp/db-llm.lock
STATUS="$OUT/STATUS.txt"
: > "$STATUS"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/driver.log.txt"; }
note() { echo "$(date +%H:%M) $*" >> "$STATUS"; }
remaining_min() { echo $(((DL - $(date +%s)) / 60)); }

finish() {
  {
    echo "finished $(date '+%Y-%m-%d %H:%M:%S') (deadline $DEADLINE_HHMM)"
    cat "$STATUS"
  } > "$OUT/DONE.txt"
  log "driver exit"
}
trap finish EXIT

# step NAME EST_MIN MAX_MIN COLLECT_ARGS...  (collect, then score with the frozen defaults)
step() {
  local name=$1 est=$2 max=$3
  shift 3
  if [ -e "$OUT/results/$name.done" ]; then
    note "$name: already done"
    return 0
  fi
  local rem
  rem=$(remaining_min)
  if [ "$rem" -lt "$est" ]; then
    log "SKIP $name (needs about $est min, $rem left)"
    note "$name: SKIPPED (deadline)"
    return 0
  fi
  local limit=$((max < rem ? max : rem))
  log "START $name (limit $limit min): $*"
  timeout $((limit * 60)) flock -w 3600 "$LOCK" $RUN collect "$@" --out "$OUT/results/$name.json" \
    > "$OUT/logs/$name.log" 2>&1
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    log "FAIL $name rc=$rc (partial results kept)"
    note "$name: FAILED rc=$rc (see logs/$name.log)"
  else
    note "$name: collected"
    touch "$OUT/results/$name.done"
  fi
  if [ -s "$OUT/results/$name.json" ]; then
    $RUN score "$OUT/results/$name.json" --baselines "$BASE" --only-split all \
      --label "$name" --report "$OUT/results/$name.score.json" --md "$OUT/results/$name.md" \
      --summary "$OUT/SUMMARY.txt" > "$OUT/logs/$name.score.log" 2>&1 || note "$name: score failed"
  fi
  log "END $name rc=$rc"
}

ensembles() {
  # every finished dev artifact together: vote / unanimity over all open-name judges
  local files
  files=$(ls "$OUT"/results/*.json 2> /dev/null | grep -v -E "score|baselines|test|curve" | tr '\n' ' ')
  # shellcheck disable=SC2086
  $RUN score $SUSPECTS/dev.json $files --baselines "$BASE" --only-split dev --label ensembles \
    --report "$OUT/ENSEMBLES_dev.json" --md "$OUT/ENSEMBLES_dev.md" > "$OUT/logs/ensembles.log" 2>&1 \
    && note "ensembles: refreshed"
}

log "driver start, deadline $(date -d @"$DL" '+%F %H:%M'), $(remaining_min) min available"
note "driver started"
timeout 10 nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader | tee -a "$OUT/driver.log.txt"
ps -eo pid,etime,user,cmd | grep -E "[p]ython|[o]llama" | cut -c1-120 | tee -a "$OUT/driver.log.txt"

# 0. wait for the running test split, then score it with the frozen defaults
while pgrep -f "[s]uspects_run.py collect --split test" > /dev/null && [ "$(remaining_min)" -gt 30 ]; do
  sleep 30
done
if [ -s "$SUSPECTS/test.json" ]; then
  $RUN collect --split all --methods none --out "$BASE" --cache-dir "$SUSPECTS/none" > "$OUT/logs/baselines.log" 2>&1
  $RUN score "$SUSPECTS/test.json" --baselines "$BASE" --only-split test --label TEST \
    --report "$OUT/TEST.score.json" --md "$OUT/TEST.md" --summary "$OUT/SUMMARY.txt" > "$OUT/logs/TEST.score.log" 2>&1
  $RUN score "$SUSPECTS/dev.json" --baselines "$BASE" --only-split dev --label DEV \
    --report "$OUT/DEV.score.json" --md "$OUT/DEV.md" --summary "$OUT/SUMMARY.txt" > "$OUT/logs/DEV.score.log" 2>&1
  note "test and dev scored with frozen defaults: TEST.md, DEV.md"
else
  note "test.json missing: the test run did not finish"
  $RUN collect --split all --methods none --out "$BASE" --cache-dir "$SUSPECTS/none" > "$OUT/logs/baselines.log" 2>&1
fi

COMMON="--split dev --variants open"
F="--methods fulltext"

# 1. thinking mode on the 8B judge
step think8b 20 50 $COMMON $F --think --suffix _think
ensembles

# 2. the 14B judge (pull once if missing, never when the disk is short)
if ! ollama list | grep -q "qwen3:14b"; then
  free_gb=$(df -BG --output=avail ~ | tail -1 | tr -dc 0-9)
  if [ "${free_gb:-0}" -gt 40 ] && [ "$(remaining_min)" -gt 60 ]; then
    log "pulling qwen3:14b (free ${free_gb} GB)"
    timeout 1800 ollama pull qwen3:14b > "$OUT/logs/pull14b.log" 2>&1 && note "qwen3:14b pulled" || note "qwen3:14b pull failed"
  else
    note "qwen3:14b pull skipped (disk ${free_gb:-?} GB or time)"
  fi
fi
if ollama list | grep -q "qwen3:14b"; then
  step full14b 30 70 $COMMON $F --model qwen3:14b --suffix _14b
else
  note "14B steps skipped: model not available"
fi
ensembles

# 3. case-file method, 8B
step dossier8b 30 70 $COMMON --methods dossier
ensembles

# 4. police-accused prior is free (baselines); pairwise tournament with 8B
step pair8b 25 60 $COMMON --methods pairwise
ensembles

# 5. self-consistency: 7 samples at temperature 0.3 for full-context and the dossier judge
step sc7 30 60 $COMMON --methods fulltext dossier --sc 7
ensembles

# 6. accuracy versus the share of text read (60, 75, 90 percent of the pre-cut text), all 16 cases
for c in 0.6 0.75 0.9; do
  step "curve_full_$c" 15 35 --split all --variants open $F --cut-frac "$c"
done
for c in 0.6 0.75 0.9; do
  step "curve_cards_$c" 15 35 $COMMON --methods cards --cut-frac "$c"
done

# 7. candidate order, two shuffles
for o in 1 2; do
  step "shuffle_$o" 10 25 $COMMON $F --shuffle-seed "$o"
done

# 8. other seeds: run-to-run noise
for sd in 7 99; do
  step "seed_full_$sd" 10 25 $COMMON $F --seed "$sd"
done
step seed_cards_7 15 35 $COMMON --methods cards --seed 7

# 9. more heavy runs while time remains: 14B pairwise, 14B thinking, more seeds
if ollama list | grep -q "qwen3:14b"; then
  step pair14b 60 100 $COMMON --methods pairwise --model qwen3:14b --suffix _14b
  step full14b_think 45 90 $COMMON $F --model qwen3:14b --think --suffix _14b_think
  step dossier14b 40 80 $COMMON --methods dossier --model qwen3:14b --suffix _14b
  step sc7_14b 40 80 $COMMON $F --model qwen3:14b --suffix _14b --sc 7
fi
ensembles
for sd in 101 202 303 404 505 606 707 808; do
  step "seed_full_$sd" 10 25 $COMMON $F --seed "$sd"
  step "seed_sc_$sd" 25 50 $COMMON --methods fulltext dossier --sc 5 --seed "$sd"
  ensembles
done
log "queue exhausted or deadline reached"
