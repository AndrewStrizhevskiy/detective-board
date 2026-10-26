#!/usr/bin/env bash
# One-time (re-runnable) setup of a GPU server for the extraction run. See docs/team/SERVER_RUNBOOK.md.
#
# Usage: scripts/server_bootstrap.sh [--check-only] [--with-8b] [--parallel N] [--keep-alive DUR]
#   --check-only   change NOTHING; print every check and what would be done (lines "WOULD: ...")
#   --with-8b      also pull qwen3:8b (upper-bound comparison)
#   --parallel N   OLLAMA_NUM_PARALLEL for the Ollama server (default 4; the probe tests 1, 2 and 4)
#   --keep-alive D OLLAMA_KEEP_ALIVE for the Ollama server (default 24h)
#   --skip-tests   skip `uv run pytest -q -m "not live"`
#
# Writes data/cache/server/bootstrap.env (read by scripts/server_run_all.sh) and bootstrap.log.
# Idempotent: every step first checks whether it is already done.
#
# Ollama facts (checked in the official docs on 2026-10-26, docs/linux.mdx and docs/faq.mdx of ollama/ollama):
#   install:     curl -fsSL https://ollama.com/install.sh | sh
#   manual:      curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | sudo tar x -C /usr
#   env vars:    OLLAMA_NUM_PARALLEL (parallel requests per model, default 1), OLLAMA_KEEP_ALIVE (e.g. 24h),
#                OLLAMA_MAX_QUEUE (default 512), OLLAMA_MAX_LOADED_MODELS
#   systemd:     `sudo systemctl edit ollama` -> [Service] Environment="OLLAMA_NUM_PARALLEL=4" ; then
#                `sudo systemctl daemon-reload && sudo systemctl restart ollama`
#   manual run:  OLLAMA_NUM_PARALLEL=4 OLLAMA_KEEP_ALIVE=24h ollama serve
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"

CHECK_ONLY=0
WITH_8B=0
SKIP_TESTS=0
PARALLEL=4
KEEP_ALIVE=24h
while [ $# -gt 0 ]; do
  case "$1" in
    --check-only) CHECK_ONLY=1; shift ;;
    --with-8b) WITH_8B=1; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    --parallel) PARALLEL="${2:?--parallel needs a number}"; shift 2 ;;
    --keep-alive) KEEP_ALIVE="${2:?--keep-alive needs a duration}"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done
case "$PARALLEL" in ''|*[!0-9]*) echo "--parallel must be a positive integer" >&2; exit 2 ;; esac
[ "$PARALLEL" -ge 1 ] || { echo "--parallel must be >= 1" >&2; exit 2; }

SERVER_DIR="$ROOT/data/cache/server"
ENV_FILE="$SERVER_DIR/bootstrap.env"
HOST_URL="${OLLAMA_HOST:-http://localhost:11434}"
case "$HOST_URL" in http*) ;; *) HOST_URL="http://$HOST_URL" ;; esac
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if [ "$CHECK_ONLY" -eq 0 ]; then
  mkdir -p "$SERVER_DIR"
  exec > >(tee -a "$SERVER_DIR/bootstrap.log") 2>&1
fi

PASSES=()
FAILS=()
WARNS=()
ok()   { echo "[ ok ] $*"; PASSES+=("$*"); }
bad()  { echo "[FAIL] $*"; FAILS+=("$*"); }
warn() { echo "[warn] $*"; WARNS+=("$*"); }
info() { echo "       $*"; }
# act "description" cmd...: run the command, or only announce it in --check-only mode
act() {
  local desc="$1"; shift
  if [ "$CHECK_ONLY" -eq 1 ]; then echo "[WOULD] $desc: $*"; return 0; fi
  echo "[ do ] $desc: $*"
  "$@"
}
have() { command -v "$1" >/dev/null 2>&1; }

echo "== 1. system"
OS_NAME="$( (. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}") || echo unknown)"
ARCH="$(uname -m)"
info "OS: $OS_NAME; kernel: $(uname -r); arch: $ARCH; user: $(id -un)"
if [ "$(uname -s)" != "Linux" ]; then bad "not Linux; these scripts target Linux servers"; fi
if [ "$ARCH" = "x86_64" ]; then ok "arch x86_64 (tarball: ollama-linux-amd64)"; else bad "arch $ARCH: the documented tarball steps below are for amd64; read https://ollama.com/download/linux"; fi
if have curl; then ok "curl present"; else bad "curl missing: install it with the distribution's package manager (or ask the admin)"; fi
if have git; then ok "git present"; else warn "git missing (not needed when the code came as a tar archive)"; fi
if have tar && have zstd; then ok "tar and zstd present (needed only for the manual tarball install)"; else info "zstd missing (only needed if Ollama must be installed from the .tar.zst tarball)"; fi
if have tmux; then ok "tmux present"; else warn "tmux missing: use the background mode (nohup, started by server_run_all.sh anyway)"; fi

SUDO="sudo"
HAVE_SUDO=0
if [ "$(id -u)" -eq 0 ]; then HAVE_SUDO=1; SUDO=""
elif have sudo && sudo -n true 2>/dev/null; then HAVE_SUDO=1; fi
if [ "$HAVE_SUDO" -eq 1 ]; then ok "root or non-interactive sudo works"; else warn "no root and no passwordless sudo: system-wide steps (Ollama install, systemd settings) cannot be done by this script"; fi

FREE_GB=$(df -Pk "$ROOT" | awk 'NR==2 {printf "%d", $4/1048576}')
info "free disk at $ROOT: ${FREE_GB} GB"
if [ "${FREE_GB:-0}" -ge 20 ]; then ok "disk: ${FREE_GB} GB free (need about 20)"; else bad "disk: only ${FREE_GB} GB free, need 20: free space or use another directory"; fi

echo "== 2. GPU"
if have nvidia-smi && nvidia-smi >/dev/null 2>&1; then
  GPU_LINE="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -1)"
  ok "GPU: $GPU_LINE"
else
  GPU_LINE=""
  bad "nvidia-smi missing or failing: NEXT STEP: install the NVIDIA driver (ALT Linux: its own driver tool; Ubuntu 24.04: 'sudo ubuntu-drivers install' then reboot). Per the runbook, if there is no working driver after 20-30 minutes, install Ubuntu 24.04. Then re-run this script"
fi

echo "== 3. uv"
if have uv; then
  ok "uv present: $(uv --version)"
else
  act "install uv (official installer)" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  if [ "$CHECK_ONLY" -eq 0 ]; then
    export PATH="$HOME/.local/bin:$PATH"
    have uv && ok "uv installed: $(uv --version)" || bad "uv install failed (internet? see https://docs.astral.sh/uv/)"
  fi
fi
if have uv; then
  act "uv sync (Python deps from uv.lock)" uv sync || bad "uv sync failed"
else
  [ "$CHECK_ONLY" -eq 1 ] && echo "[WOULD] uv sync"
fi

echo "== 4. Ollama install"
MANUAL_STEPS='Documented manual install (https://ollama.com/download/linux, docs/linux.mdx of ollama/ollama), needs root:
    curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | sudo tar x -C /usr
    sudo useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
    sudo usermod -a -G ollama $(whoami)
    # then create /etc/systemd/system/ollama.service exactly as in the docs and:
    #   sudo systemctl daemon-reload && sudo systemctl enable --now ollama
  Without root and without systemd the same binary can only be run by whoever may unpack it: ask the admin to run the first
  line (or to run the official installer: curl -fsSL https://ollama.com/install.sh | sh), then re-run this script.'
if have ollama; then
  ok "ollama present: $(ollama --version 2>&1 | tail -1) (reference laptop: 0.35.0)"
elif [ "$HAVE_SUDO" -eq 1 ]; then
  act "install Ollama (official installer)" bash -c 'curl -fsSL https://ollama.com/install.sh | sh'
  if [ "$CHECK_ONLY" -eq 0 ]; then
    have ollama && ok "ollama installed: $(ollama --version 2>&1 | tail -1)" || bad "Ollama installer finished but 'ollama' is not on PATH"
  fi
else
  bad "ollama missing and there is no root/sudo. $MANUAL_STEPS"
fi

echo "== 5. Ollama server: concurrency settings, GPU"
SYSTEMD_SERVICE=0
if have systemctl && systemctl list-unit-files ollama.service >/dev/null 2>&1 \
   && systemctl list-unit-files ollama.service 2>/dev/null | grep -q '^ollama.service'; then
  SYSTEMD_SERVICE=1
fi
want_env() { # prints the current Environment of the running server, one VAR=VAL per line
  if [ "$SYSTEMD_SERVICE" -eq 1 ]; then
    systemctl show ollama -p Environment --value 2>/dev/null | tr ' ' '\n'
  else
    local pid; pid="$(pgrep -x ollama | head -1)"
    [ -n "$pid" ] && tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null
  fi
}
CUR_ENV="$(want_env || true)"
cur_par="$(printf '%s\n' "$CUR_ENV" | sed -n 's/^"\{0,1\}OLLAMA_NUM_PARALLEL=\([0-9]*\).*/\1/p' | head -1)"
cur_ka="$(printf '%s\n' "$CUR_ENV" | sed -n 's/^"\{0,1\}OLLAMA_KEEP_ALIVE=\([^"]*\).*/\1/p' | head -1)"
server_up() { curl -fsS -m 3 "$HOST_URL/api/version" >/dev/null 2>&1; }
MODE=manual
[ "$SYSTEMD_SERVICE" -eq 1 ] && MODE=systemd
info "server mode: $MODE; running: $(server_up && echo yes || echo no); current NUM_PARALLEL=${cur_par:-unset(1)} KEEP_ALIVE=${cur_ka:-unset}"

if have ollama; then
  if [ "$MODE" = systemd ]; then
    if [ "${cur_par:-}" = "$PARALLEL" ] && [ "${cur_ka:-}" = "$KEEP_ALIVE" ] && server_up; then
      ok "systemd service already has OLLAMA_NUM_PARALLEL=$PARALLEL, OLLAMA_KEEP_ALIVE=$KEEP_ALIVE"
    elif [ "$HAVE_SUDO" -eq 1 ]; then
      OVR=/etc/systemd/system/ollama.service.d/override.conf
      act "write $OVR" bash -c "$SUDO mkdir -p /etc/systemd/system/ollama.service.d && printf '[Service]\nEnvironment=\"OLLAMA_NUM_PARALLEL=$PARALLEL\"\nEnvironment=\"OLLAMA_KEEP_ALIVE=$KEEP_ALIVE\"\n' | $SUDO tee $OVR >/dev/null"
      act "reload and restart the service" bash -c "$SUDO systemctl daemon-reload && $SUDO systemctl enable --now ollama && $SUDO systemctl restart ollama"
    else
      bad "systemd Ollama needs OLLAMA_NUM_PARALLEL=$PARALLEL but there is no sudo. Ask the admin: sudo systemctl edit ollama  (add under [Service]: Environment=\"OLLAMA_NUM_PARALLEL=$PARALLEL\" and Environment=\"OLLAMA_KEEP_ALIVE=$KEEP_ALIVE\"), then sudo systemctl daemon-reload && sudo systemctl restart ollama; or stop it and use 'ollama serve' manually"
    fi
  else
    PIDFILE="$SERVER_DIR/ollama-serve.pid"
    if server_up && [ "${cur_par:-}" = "$PARALLEL" ] && [ "${cur_ka:-}" = "$KEEP_ALIVE" ]; then
      ok "manual 'ollama serve' already running with OLLAMA_NUM_PARALLEL=$PARALLEL, OLLAMA_KEEP_ALIVE=$KEEP_ALIVE"
    elif server_up; then
      if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        act "stop our previous 'ollama serve' (settings differ)" kill "$(cat "$PIDFILE")"
        [ "$CHECK_ONLY" -eq 0 ] && sleep 3
        act "start 'ollama serve' with the right settings (log: $SERVER_DIR/ollama-serve.log)" bash -c "OLLAMA_NUM_PARALLEL=$PARALLEL OLLAMA_KEEP_ALIVE=$KEEP_ALIVE setsid nohup ollama serve >>'$SERVER_DIR/ollama-serve.log' 2>&1 & echo \$! >'$PIDFILE'"
      else
        bad "an Ollama server is running with unknown or different settings (NUM_PARALLEL=${cur_par:-unset}) and it was not started by this script. Stop it, then re-run; or re-run with --parallel ${cur_par:-1} to accept its setting"
      fi
    else
      act "start 'ollama serve' with OLLAMA_NUM_PARALLEL=$PARALLEL OLLAMA_KEEP_ALIVE=$KEEP_ALIVE (log: $SERVER_DIR/ollama-serve.log)" bash -c "OLLAMA_NUM_PARALLEL=$PARALLEL OLLAMA_KEEP_ALIVE=$KEEP_ALIVE setsid nohup ollama serve >>'$SERVER_DIR/ollama-serve.log' 2>&1 & echo \$! >'$PIDFILE'"
    fi
  fi
  if [ "$CHECK_ONLY" -eq 0 ]; then
    for _ in $(seq 1 30); do server_up && break; sleep 1; done
    server_up && ok "Ollama answers at $HOST_URL (version $(curl -fsS "$HOST_URL/api/version" | sed 's/.*"version":"\([^"]*\)".*/\1/'))" || bad "Ollama does not answer at $HOST_URL; see journalctl -e -u ollama or $SERVER_DIR/ollama-serve.log"
  fi
  if [ -n "${OLLAMA_HOST:-}" ]; then warn "OLLAMA_HOST is set ($OLLAMA_HOST): extract.run and the shard script use http://localhost:11434 unless EXTRA_ARGS has --host"; fi
fi

echo "== 6. models"
REQUIRED=(qwen3:4b qwen3:4b-instruct bge-m3)
[ "$WITH_8B" -eq 1 ] && REQUIRED+=(qwen3:8b)
if have ollama && { server_up || [ "$CHECK_ONLY" -eq 0 ]; }; then
  LIST_FILE="$(mktemp)"
  ollama list >"$LIST_FILE" 2>&1 || true
  for m in "${REQUIRED[@]}"; do
    if grep -q "^$m\(:latest\)\? " "$LIST_FILE"; then info "$m already pulled"; else act "pull $m" ollama pull "$m" || bad "ollama pull $m failed (internet?)"; fi
  done
  if [ "$CHECK_ONLY" -eq 0 ]; then ollama list >"$LIST_FILE" 2>&1; fi
  if CMP="$(uv run python scripts/server_report.py check-models --list "$LIST_FILE" "${REQUIRED[@]}" 2>&1)"; then
    ok "model IDs match docs/team/models.md"; echo "$CMP" | sed 's/^/       /'
  else
    echo "$CMP" | sed 's/^/       /'
    if [ "$CHECK_ONLY" -eq 1 ]; then warn "model IDs not matching yet (expected before the pull): see lines above"; else bad "MODEL ID MISMATCH or missing model: cached outputs would not be comparable. Do not start the full run; tell the lead"; fi
  fi
  rm -f "$LIST_FILE"
else
  echo "[WOULD] ollama pull ${REQUIRED[*]}; compare IDs with docs/team/models.md (scripts/server_report.py check-models)"
fi

echo "== 7. tests"
if [ "$SKIP_TESTS" -eq 1 ]; then
  info "skipped (--skip-tests)"
elif have uv; then
  if [ "$CHECK_ONLY" -eq 1 ]; then echo "[WOULD] run the offline test suite: uv run pytest -q -m \"not live\""
  elif uv run pytest -q -m "not live"; then ok "pytest (not live) green"; else bad "pytest failed"; fi
else
  echo "[WOULD] uv run pytest -q -m \"not live\""
fi

echo "== 8. GPU actually used"
if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "[WOULD] send a 1-token request to qwen3:4b and require 'ollama ps' to show GPU in the PROCESSOR column"
elif have ollama && server_up; then
  if curl -fsS -m 300 "$HOST_URL/api/generate" -d '{"model":"qwen3:4b","prompt":"hi","stream":false,"think":false,"options":{"num_predict":1}}' >/dev/null; then
    PS="$(ollama ps)"; echo "$PS" | sed 's/^/       /'
    if echo "$PS" | grep '^qwen3:4b ' | grep -q '100% GPU'; then
      ok "qwen3:4b is loaded 100% on the GPU"
    else
      bad "qwen3:4b is NOT 100% on the GPU (see PROCESSOR above): check nvidia-smi, the driver and 'journalctl -e -u ollama'; do not start the run"
    fi
  else
    bad "the 1-token request failed (model missing or server error)"
  fi
else
  bad "cannot test the GPU: no Ollama server"
fi

if [ "$CHECK_ONLY" -eq 0 ]; then
  {
    echo "OLLAMA_NUM_PARALLEL=$PARALLEL"
    echo "OLLAMA_KEEP_ALIVE=$KEEP_ALIVE"
    echo "OLLAMA_MODE=$MODE"
    echo "BOOTSTRAP_GPU=\"$GPU_LINE\""
    echo "BOOTSTRAP_OK=$([ ${#FAILS[@]} -eq 0 ] && echo 1 || echo 0)"
  } >"$ENV_FILE"
fi

echo
echo "== SUMMARY ($([ "$CHECK_ONLY" -eq 1 ] && echo check-only || echo applied)): ${#PASSES[@]} ok, ${#WARNS[@]} warnings, ${#FAILS[@]} failures"
for w in "${WARNS[@]}"; do echo "  warn: $w"; done
if [ ${#FAILS[@]} -gt 0 ]; then
  for f in "${FAILS[@]}"; do echo "  FAIL: $f"; done
  echo "RESULT: FAIL"
  exit 1
fi
if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "RESULT: checks passed (nothing was changed). Lines marked WOULD show what a real run does."
  echo "NEXT: scripts/server_bootstrap.sh"
else
  echo "RESULT: PASS"
  echo "NEXT: scripts/server_run_all.sh      (run it inside tmux: tmux new -s extract)"
fi
