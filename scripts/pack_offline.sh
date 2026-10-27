#!/usr/bin/env bash
# Build the offline archive: everything the demo laptop needs with the network cable unplugged.
# Usage: scripts/pack_offline.sh [--tag REF] [--out DIR] [--with-8b] [--dry-run]
#   --tag REF   commit or tag to pack (default HEAD); the source is `git archive REF`
#   --out DIR   where to build (default dist/); the result is DIR/detective-board-offline-<ref>.tar
#   --with-8b   also pack qwen3:8b (optional upper-bound model, 5.2 GB)
#   --dry-run   only check that every input exists and print the plan (works on any OS)
# Contents: the repo at REF (with the web/replay recordings), data/index/db.sqlite,
# data/index/sentences.sqlite, data/graph/graph.sqlite, uv, a Python build (uv python install), a
# uv cache for an offline `uv sync`, the Ollama binary and only the needed models (bge-m3,
# qwen3:4b-instruct, qwen3:4b; IDs checked against docs/team/models.md), INSTALL.md, MANIFEST and
# SHA256SUMS (every file).
# Must run on Linux x86_64 (the target platform): uv installs a Python for the host it runs on,
# and the uv, Ollama and wheel binaries must match the laptop. Fails if any model or data file is
# missing. Check the result on the target with scripts/verify_offline.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

REF="HEAD"
OUT="dist"
WITH_8B=0
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) REF="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --with-8b) WITH_8B=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

MODELS=("bge-m3:latest" "qwen3:4b-instruct" "qwen3:4b")
[ "$WITH_8B" -eq 1 ] && MODELS+=("qwen3:8b")
DATA=("data/index/db.sqlite" "data/index/sentences.sqlite" "data/graph/graph.sqlite")
OLLAMA_MODELS_DIR="${OLLAMA_MODELS:-}"
if [ -z "$OLLAMA_MODELS_DIR" ]; then
  for d in "$HOME/.ollama/models" /usr/share/ollama/.ollama/models; do
    [ -d "$d/manifests" ] && OLLAMA_MODELS_DIR="$d" && break
  done
fi

problems=()
note() { echo "  $*"; }

# ---------------------------------------------------------------- inputs
COMMIT="$(git rev-parse --verify "$REF^{commit}" 2>/dev/null)" || { echo "unknown ref: $REF" >&2; exit 2; }
SAFE_REF="$(echo "$REF" | tr -c 'A-Za-z0-9._-' '-' | sed 's/-*$//')"
[ "$REF" = "HEAD" ] && SAFE_REF="${COMMIT:0:12}"
echo "pack: ref $REF = $COMMIT"
for f in "${DATA[@]}"; do
  if [ -f "$f" ]; then note "data  $f ($(du -h "$f" | cut -f1))"; else problems+=("missing data file: $f"); fi
done
UV_BIN="$(command -v uv || true)"
[ -n "$UV_BIN" ] && note "uv    $UV_BIN ($(uv --version))" || problems+=("uv not found on PATH")
OLLAMA_BIN="$(command -v ollama || true)"
if [ -n "$OLLAMA_BIN" ]; then
  note "ollama $OLLAMA_BIN ($(ollama --version 2>/dev/null | tail -n 1))"
else
  problems+=("ollama not found on PATH")
fi
PYVER="$(cat .python-version)"
note "python $PYVER (uv python install)"

# expected model IDs: the ID column of docs/team/models.md (12-char prefix of the manifest sha256)
expected_id() {
  sed -n "s/^| \`$1\` | [^|]* | \`\([0-9a-f]\{12\}\)\` |.*/\1/p" docs/team/models.md | head -n 1
}
manifest_path() {
  local name="${1%%:*}" tag="${1#*:}"
  [ "$name" = "$1" ] && tag="latest"
  echo "$OLLAMA_MODELS_DIR/manifests/registry.ollama.ai/library/$name/$tag"
}
sha256_of() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
for m in "${MODELS[@]}"; do
  want="$(expected_id "$m")"
  mf="$(manifest_path "$m")"
  if [ -z "$want" ]; then
    problems+=("model $m: no ID pinned in docs/team/models.md")
    continue
  fi
  if [ -z "$OLLAMA_MODELS_DIR" ]; then
    problems+=("model $m: no Ollama models folder found (set OLLAMA_MODELS)")
    continue
  fi
  if [ ! -f "$mf" ]; then
    problems+=("model not pulled: $m (no manifest at $mf)")
    continue
  fi
  have="$(sha256_of "$mf" | cut -c1-12)"
  if [ "$have" != "$want" ]; then
    problems+=("model $m has ID $have, docs/team/models.md pins $want")
  else
    note "model $m ID $have"
  fi
done

if [ "${#problems[@]}" -gt 0 ]; then
  echo "NOT READY:"
  for p in "${problems[@]}"; do echo "  - $p"; done
  exit 2
fi
if [ "$DRY" -eq 1 ]; then
  echo "dry run: every input is present"
  exit 0
fi
if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "pack on Linux x86_64 (the target platform); this host is $(uname -s) $(uname -m)" >&2
  exit 2
fi

# ---------------------------------------------------------------- build
NAME="detective-board-offline-$SAFE_REF"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
DIST="$OUT/$NAME"
[ -e "$DIST" ] && { echo "$DIST exists; remove it first" >&2; exit 2; }
mkdir -p "$DIST"/{bin,ollama/bin,ollama-models}
echo "build: $DIST"

# source at REF (tracked files only) plus the git-ignored data the demo needs
git archive --format=tar --prefix=detective-board/ "$COMMIT" | tar -x -C "$DIST"
echo "$COMMIT" > "$DIST/detective-board/COMMIT"
for f in "${DATA[@]}"; do mkdir -p "$DIST/detective-board/$(dirname "$f")"; cp "$f" "$DIST/detective-board/$f"; done

# uv, a Python build, and a uv cache holding every locked wheel (runtime + dev group, for the
# test subset of the check) plus the build backend for the editable project install. An offline
# `uv sync` installs locked packages from the cache; it does not take them from --find-links.
cp -L "$UV_BIN" "$DIST/bin/uv"
UVX_BIN="$(command -v uvx || true)"; [ -n "$UVX_BIN" ] && cp -L "$UVX_BIN" "$DIST/bin/uvx"
"$DIST/bin/uv" python install "$PYVER" --install-dir "$DIST/python" --no-bin
# uv also leaves an absolute symlink cpython-<ver>-<platform> next to the build; dangling once moved
find "$DIST/python" -maxdepth 1 -type l -delete
PY="$(ls -d "$DIST"/python/cpython-*/bin/python3 | head -n 1)"
# --no-config: no uv.toml or index setting of the packing machine leaks into the cache
(cd "$DIST/detective-board" && UV_CACHE_DIR="$DIST/uv-cache" "$DIST/bin/uv" sync --locked --group dev \
  --no-config --python "$PY" && rm -rf .venv)

# Ollama: the binary, its runner libraries, and only the needed models
OLLAMA_REAL="$(readlink -f "$OLLAMA_BIN")"
cp "$OLLAMA_REAL" "$DIST/ollama/bin/ollama"
# lib/ollama holds the CPU runners too, so it must exist (GPU runtimes in it are copied as well)
LIBDIR="$(dirname "$OLLAMA_REAL")/../lib/ollama"
[ -d "$LIBDIR" ] || { echo "no $LIBDIR next to the Ollama binary; Ollama cannot run without it" >&2; exit 2; }
mkdir -p "$DIST/ollama/lib" && cp -a "$LIBDIR" "$DIST/ollama/lib/"
for m in "${MODELS[@]}"; do
  mf="$(manifest_path "$m")"
  rel="${mf#"$OLLAMA_MODELS_DIR"/}"
  mkdir -p "$DIST/ollama-models/$(dirname "$rel")"
  cp "$mf" "$DIST/ollama-models/$rel"
  "$PY" - "$mf" <<'PY' | while read -r digest; do
import json, sys
m = json.load(open(sys.argv[1]))
for layer in [m["config"], *m["layers"]]:
    print(layer["digest"].replace(":", "-"))
PY
    mkdir -p "$DIST/ollama-models/blobs"
    [ -f "$DIST/ollama-models/blobs/$digest" ] || cp "$OLLAMA_MODELS_DIR/blobs/$digest" "$DIST/ollama-models/blobs/$digest"
  done
done

# instructions, the check, the manifest and the checksums
cp docs/team/CLEAN_INSTALL.md "$DIST/INSTALL.md"
cp scripts/verify_offline.sh "$DIST/verify_offline.sh"
{
  echo "commit $COMMIT"
  echo "ref $REF"
  echo "built $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(uname -srm)"
  echo "uv $("$DIST/bin/uv" --version)"
  echo "python $("$PY" -c 'import sys; print(sys.version.split()[0])')"
  echo "ollama $("$OLLAMA_BIN" --version 2>/dev/null | tail -n 1)"
  for m in "${MODELS[@]}"; do echo "model $m $(sha256_of "$(manifest_path "$m")" | cut -c1-12)"; done
} > "$DIST/MANIFEST"
# uv rewrites its cache .lock files on every run, so they are not checksummed
(cd "$DIST" && find . -type f ! -name SHA256SUMS ! -name .lock -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

tar -cf "$OUT/$NAME.tar" -C "$OUT" "$NAME"
(cd "$OUT" && sha256sum "$NAME.tar" > "$NAME.tar.sha256")
echo "archive: $OUT/$NAME.tar ($(du -h "$OUT/$NAME.tar" | cut -f1)); checksum in $OUT/$NAME.tar.sha256"
echo "next: copy it to the laptop, unpack, run ./verify_offline.sh with the network off"
