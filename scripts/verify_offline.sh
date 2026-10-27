#!/usr/bin/env bash
# Check an unpacked offline archive on the target laptop, with the network off.
# Usage: ./verify_offline.sh [ARCHIVE_DIR] [--require-offline] [--port N] [--ollama-port N] [--keep]
#   ARCHIVE_DIR        the unpacked detective-board-offline-<ref>/ (default: this script's folder)
#   --require-offline  FAIL (not just warn) if the internet is reachable
#   --port N           API port for the check (default 8765); --ollama-port N (default 11435)
#   --keep             leave Ollama and the API running afterwards
# Steps: checksums of every file (SHA256SUMS); offline `uv sync` from the packed uv cache with the
# bundled Python; the fast test subset; Ollama from the archive with the archive's models, IDs
# compared with MANIFEST; what `just run` does (preflight, API) on the real index and graph; the
# three scripted demo questions (g001 answered, c001 with R1 violated, g047 refused) plus a second
# refusal (g056). Prints PASS/FAIL per step; exit 0 only when all pass.
# Run it with no network: unplug the cable, or (Linux) `unshare -rn sh -c 'ip link set lo up && ./verify_offline.sh'`.
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REQUIRE_OFFLINE=0
PORT=8765
OPORT=11435
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --require-offline) REQUIRE_OFFLINE=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --ollama-port) OPORT="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) DIR="$(cd "$1" && pwd)" || { echo "no such folder: $1" >&2; exit 2; }; shift ;;
  esac
done
REPO="$DIR/detective-board"
LOG="$DIR/verify-logs"
mkdir -p "$LOG"
RESULTS=()
FAILED=0
pass() { RESULTS+=("PASS  $1"); echo "PASS  $1"; }
fail() { RESULTS+=("FAIL  $1"); echo "FAIL  $1"; FAILED=1; }
warn() { RESULTS+=("WARN  $1"); echo "WARN  $1"; }
PIDS=()
cleanup() { [ "$KEEP" -eq 1 ] || for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done; }
trap cleanup EXIT
t0=$(date +%s)

# 1. every file is what was packed
if (cd "$DIR" && sha256sum -c --quiet SHA256SUMS >"$LOG/checksums.txt" 2>&1); then
  pass "checksums: $(wc -l < "$DIR/SHA256SUMS") files match SHA256SUMS"
else
  fail "checksums: see $LOG/checksums.txt"
fi

# 2. the network really is off
if curl -sS -m 3 -o /dev/null https://pypi.org 2>/dev/null; then
  if [ "$REQUIRE_OFFLINE" -eq 1 ]; then fail "network: the internet is reachable"; else warn "network: the internet is reachable; this run does not prove offline operation"; fi
else
  pass "network: no internet"
fi

# 3. Python environment from the packed uv cache, nothing downloaded
export UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR="$DIR/uv-cache"
PY="$(ls -d "$DIR"/python/cpython-*/bin/python3 2>/dev/null | head -n 1)"
UV="$DIR/bin/uv"
if [ -n "$PY" ] && (cd "$REPO" && "$UV" sync --locked --group dev --offline --python "$PY" >"$LOG/uv-sync.txt" 2>&1); then
  pass "uv sync offline with $("$PY" -c 'import sys; print(sys.version.split()[0])')"
else
  fail "uv sync offline: see $LOG/uv-sync.txt"
fi

# 4. the fast tests (no Ollama needed)
if (cd "$REPO" && "$UV" run --offline --no-sync pytest -q -m "not live and not e2e" >"$LOG/pytest.txt" 2>&1); then
  pass "tests: $(tail -n 1 "$LOG/pytest.txt")"
else
  fail "tests: $(tail -n 1 "$LOG/pytest.txt") (see $LOG/pytest.txt)"
fi

# 5. Ollama from the archive with the archive's models
export OLLAMA_MODELS="$DIR/ollama-models" OLLAMA_HOST="127.0.0.1:$OPORT"
"$DIR/ollama/bin/ollama" serve >"$LOG/ollama.txt" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 60); do curl -s -m 2 "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break; sleep 1; done
"$DIR/ollama/bin/ollama" list >"$LOG/ollama-list.txt" 2>&1
models_ok=1
while read -r kind tag id; do
  [ "$kind" = "model" ] || continue
  if awk -v t="$tag" -v i="$id" '$1==t && $2==i {f=1} END {exit !f}' "$LOG/ollama-list.txt"; then :; else models_ok=0; echo "  $tag: expected ID $id"; fi
done < "$DIR/MANIFEST"
if [ "$models_ok" -eq 1 ]; then pass "ollama: models match MANIFEST ($(grep -c '^model ' "$DIR/MANIFEST"))"; else fail "ollama: model IDs differ (see $LOG/ollama-list.txt)"; fi

# 6. what `just run` does (preflight, then the API) on the real index and graph; the three
# scripted demo questions (docs/design/demo-script.md) plus a second refusal
export DETECTIVE_BOARD_OLLAMA_HOST="http://$OLLAMA_HOST"
if (cd "$REPO" && "$UV" run --offline --no-sync python scripts/preflight.py >"$LOG/preflight.txt" 2>&1); then
  pass "preflight: Ollama and the configured models answer"
else
  fail "preflight: see $LOG/preflight.txt"
fi
# exec: $! is then uv itself (it forwards SIGTERM to the API), not a subshell that cleanup would orphan
(cd "$REPO" && exec "$UV" run --offline --no-sync python -m detective_board.api --host 127.0.0.1 --port "$PORT" >"$LOG/api.txt" 2>&1) &
PIDS+=($!)
for _ in $(seq 1 120); do curl -s -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break; sleep 1; done
if (cd "$REPO" && "$UV" run --offline --no-sync python - "$PORT" >"$LOG/ask.txt" 2>&1) <<'PY'
import json, sys, time, urllib.request
port = sys.argv[1]
golden = {}
for name in ("questions", "contradictions"):
    golden.update({q["id"]: q for q in map(json.loads, open(f"eval/golden/{name}.jsonl"))})
# id, wanted final status, rule that must report "violated" (None: no rule check)
CASES = (("g001", "answered", None), ("c001", None, "R1"), ("g047", "refused", None), ("g056", "refused", None))
ok = True
for qid, want, rule in CASES:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ask", json.dumps({"question": golden[qid]["question"]}).encode(), {"Content-Type": "application/json"})
    t0, final, verdicts = time.time(), None, []
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                if ev.get("type") == "final":
                    final = ev
                elif ev.get("type") == "tool_result" and isinstance(ev.get("explanation"), dict):
                    verdicts.append((ev["explanation"].get("rule_id"), ev["explanation"].get("verdict")))
    except OSError as e:  # HTTP errors and timeouts: report this case, go on with the next
        final = {"status": f"request failed: {e}"}
    got = final and final.get("status")
    good = got is not None and got != "error" and (want is None or got == want)
    if rule:
        good = good and (rule, "violated") in verdicts
    print(f"{qid}: {got} in {time.time() - t0:.1f} s" + (f", rules {verdicts}" if rule else "") + f" ({'ok' if good else 'WANT ' + (want or rule + ' violated')})")
    ok = ok and good
sys.exit(0 if ok else 1)
PY
then
  pass "api: $(tr '\n' ';' < "$LOG/ask.txt")"
else
  fail "api: $(tr '\n' ';' < "$LOG/ask.txt") (see $LOG/api.txt)"
fi

echo
echo "== verify_offline: $(hostname) $(date -u +%Y-%m-%dT%H:%M:%SZ), $(( $(date +%s) - t0 )) s, $(head -n 1 "$DIR/MANIFEST")"
printf '%s\n' "${RESULTS[@]}"
if [ "$FAILED" -eq 0 ]; then echo "RESULT: PASS"; exit 0; else echo "RESULT: FAIL"; exit 1; fi
