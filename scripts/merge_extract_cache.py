#!/usr/bin/env python3
"""Merge / verify extraction caches (SQLite `raw(key, value)`, see extract/cache.py).

A cache key is a sha256 of (chunk text, model, prompt version, schema version, options), so the
key parts are not stored. To refuse foreign entries we recompute the expected key of every chunk
in --chunks for the given --model/--prompt/options and only accept keys from that set. Entries
with other keys (different model, prompt, schema version, options, or unknown chunk text) are
foreign: merge aborts unless --force.

  merge   DEST SRC [SRC...] --model M [--chunks ...] [--prompt ...] [--force] [--dry-run]
  verify  CACHE_A CACHE_B --model M [-n 3] [--story S]   compare raw outputs of N chunks
  count   CACHE [CACHE...]                               entry counts

Merge is idempotent: existing keys are never overwritten (a differing value for an existing key is
reported as a conflict and the destination value is kept).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from detective_board.extract import schema_v2  # noqa: E402
from detective_board.extract.cache import ExtractCache, cache_key  # noqa: E402
from detective_board.extract.pipeline import DEFAULT_PROMPT, ExtractConfig, load_prompt  # noqa: E402


def expected_keys(
    chunks: Path, cfg: ExtractConfig, prompt_version: str, story: str | None = None
) -> dict[str, str]:
    """key -> chunk_id for every chunk, under the given config."""
    out: dict[str, str] = {}
    with open(chunks, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if story and rec.get("story") != story:
                continue
            k = cache_key(
                rec["text"], cfg.model, prompt_version, schema_v2.SCHEMA_VERSION, cfg.options()
            )
            out[k] = rec["chunk_id"]
    return out


@dataclass
class MergeReport:
    added: int = 0
    already_present: int = 0
    conflicts: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)
    foreign_merged: int = 0
    total_dest: int = 0

    def line(self) -> str:
        return (
            f"added={self.added} already_present={self.already_present} "
            f"conflicts={len(self.conflicts)} foreign={len(self.foreign)} "
            f"foreign_merged={self.foreign_merged} dest_total={self.total_dest}"
        )


def _rows(path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT key, value FROM raw ORDER BY key").fetchall()
    finally:
        conn.close()


def merge_caches(
    dest: Path,
    srcs: list[Path],
    expected: dict[str, str],
    force: bool = False,
    dry_run: bool = False,
) -> MergeReport:
    """Merge SRC caches into DEST. Raises ValueError on foreign keys unless force."""
    rep = MergeReport()
    plan: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    existing: dict[str, str] = dict(_rows(dest)) if dest.exists() else {}
    for src in srcs:
        for key, value in _rows(src):
            is_foreign = key not in expected
            if is_foreign:
                rep.foreign.append(key)
                if not force:
                    continue
            if key in existing or key in seen:
                prev = existing.get(key, seen.get(key))
                if prev == value:
                    rep.already_present += 1
                else:
                    rep.conflicts.append(key)
                continue
            seen[key] = value
            plan.append((key, value))
            if is_foreign:
                rep.foreign_merged += 1
    if rep.foreign and not force:
        raise ValueError(
            f"{len(rep.foreign)} entries do not match the expected model/prompt/schema/options "
            "(or are unknown chunks); nothing merged. Use --force to merge anyway."
        )
    rep.added = len(plan)
    if dry_run:
        rep.total_dest = len(existing) + rep.added
        return rep
    cache = ExtractCache(dest)
    try:
        with cache.conn:
            cache.conn.executemany("INSERT OR IGNORE INTO raw(key, value) VALUES (?,?)", plan)
        rep.total_dest = len(cache)
    finally:
        cache.close()
    return rep


@dataclass
class VerifyReport:
    compared: int = 0
    identical: int = 0
    different: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def verify_caches(a: Path, b: Path, expected: dict[str, str], n: int) -> VerifyReport:
    """Compare the raw model text of up to n chunks present in both caches."""
    ra, rb = dict(_rows(a)), dict(_rows(b))
    rep = VerifyReport()
    for key, cid in expected.items():
        if rep.compared >= n:
            break
        if key not in ra or key not in rb:
            if key in ra or key in rb:
                rep.missing.append(cid)
            continue
        rep.compared += 1
        if json.loads(ra[key])["text"] == json.loads(rb[key])["text"]:
            rep.identical += 1
        else:
            rep.different.append(cid)
    return rep


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", required=True, help="exact Ollama tag, e.g. qwen3:4b")
    p.add_argument("--chunks", type=Path, default=ROOT / "data" / "chunks.jsonl")
    p.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    p.add_argument("--num-ctx", type=int, default=4096)
    p.add_argument("--num-predict", type=int, default=1536)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--story")


def _expected(a: argparse.Namespace) -> dict[str, str]:
    cfg = ExtractConfig(a.model, a.num_ctx, a.num_predict, a.seed)
    return expected_keys(a.chunks, cfg, load_prompt(a.prompt).version, a.story)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("dest", type=Path)
    m.add_argument("srcs", type=Path, nargs="+")
    m.add_argument("--force", action="store_true")
    m.add_argument("--dry-run", action="store_true")
    _common(m)
    v = sub.add_parser("verify")
    v.add_argument("cache_a", type=Path)
    v.add_argument("cache_b", type=Path)
    v.add_argument("-n", type=int, default=3)
    _common(v)
    c = sub.add_parser("count")
    c.add_argument("caches", type=Path, nargs="+")
    a = ap.parse_args(argv)

    if a.cmd == "count":
        for p in a.caches:
            print(f"{p}: {len(_rows(p)) if p.exists() else 0}")
        return 0
    exp = _expected(a)
    if a.cmd == "merge":
        missing = [s for s in a.srcs if not s.exists()]
        if missing:
            print(f"missing source cache(s): {missing}", file=sys.stderr)
            return 2
        try:
            rep = merge_caches(a.dest, a.srcs, exp, a.force, a.dry_run)
        except ValueError as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return 1
        print(("DRY-RUN " if a.dry_run else "") + rep.line())
        print(f"expected chunk keys for this config: {len(exp)}")
        return 1 if rep.conflicts else 0
    rep = verify_caches(a.cache_a, a.cache_b, exp, a.n)
    print(
        f"compared={rep.compared} identical={rep.identical} different={len(rep.different)} "
        f"present_in_one_only={len(rep.missing)}"
    )
    for cid in rep.different:
        print(f"  DIFFERENT raw output: {cid}")
    return 0 if rep.compared and not rep.different else 1


if __name__ == "__main__":
    raise SystemExit(main())
