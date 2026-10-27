#!/usr/bin/env bash
# Build the archive to carry to the department server and prove that it works from a clean copy.
# Usage: scripts/make_server_archive.sh [--no-verify] [OUT.tar.gz]
# The archive is `git archive HEAD` (tracked files only: no .git, no secrets, no local caches) plus a COMMIT file.
# Verification: unpack into a temp dir, `uv sync`, run the fast test suite there, `bash -n` on the server scripts.
set -u
cd "$(dirname "$0")/.."
VERIFY=1
OUT="detective-board.tar.gz"
for a in "$@"; do
  case "$a" in
    --no-verify) VERIFY=0 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) OUT="$a" ;;
  esac
done
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "WARNING: tracked files have uncommitted changes; they are NOT in the archive (git archive uses HEAD)"
fi
TMP="$(mktemp -d)"
git rev-parse HEAD > "$TMP/COMMIT"
git archive --format=tar.gz --add-file="$TMP/COMMIT" -o "$OUT" HEAD
echo "archive: $OUT ($(du -h "$OUT" | cut -f1)), commit $(cat "$TMP/COMMIT")"
sha256sum "$OUT"
if [ "$VERIFY" -eq 1 ]; then
  W="$(mktemp -d)"
  tar xzf "$OUT" -C "$W"
  ( cd "$W" && bash -n scripts/server_bootstrap.sh && bash -n scripts/server_run_all.sh && bash -n scripts/server_progress.sh \
      && bash -n scripts/extract_shard.sh && bash -n scripts/server_presence.sh && echo "bash -n: ok" \
      && uv sync -q && echo "uv sync: ok" && uv run pytest -q -m "not live" 2>&1 | tail -n 2 \
      && scripts/server_bootstrap.sh --check-only 2>&1 | tail -n 4 ) || { echo "VERIFY FAILED in $W"; exit 1; }
  echo "verified from a clean copy: $W"
fi
