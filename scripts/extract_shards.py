#!/usr/bin/env python3
"""Plan extraction shards: split the priority story list into N shards balanced by chunk count.

The story order is read from scripts/run_extraction_priority.sh (single source of truth).
Assignment is greedy longest-processing-time: heaviest story first, into the lightest shard
(ties: lower shard id). Inside a shard stories keep the priority order.

Usage:
  extract_shards.py stories <shard-id> <n-shards>   # story slugs of one shard, one per line
  extract_shards.py plan <n-shards>                 # human-readable table
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIORITY_SH = ROOT / "scripts" / "run_extraction_priority.sh"
CHUNKS = ROOT / "data" / "chunks.jsonl"


def priority_stories(path: Path = PRIORITY_SH) -> list[str]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"STORIES=\((.*?)\)", text, re.S)
    if not m:
        raise ValueError(f"no STORIES=(...) array in {path}")
    body = m.group(1).replace("\\", " ")
    # the runner allows `STORIES=(${ORDER:-<default list>})`: the default list is the truth
    body = re.sub(r"^\s*\$\{ORDER:-", "", body.strip())
    return body.rstrip("}").split()


def chunk_counts(path: Path = CHUNKS) -> Counter:
    c: Counter = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c[json.loads(line)["story"]] += 1
    return c


def plan_shards(stories: list[str], counts: dict[str, int], n: int) -> list[list[str]]:
    """Return n lists of stories (priority order inside each), balanced by chunk count."""
    if n < 1:
        raise ValueError("n must be >= 1")
    rank = {s: i for i, s in enumerate(stories)}
    loads = [0] * n
    shards: list[list[str]] = [[] for _ in range(n)]
    for s in sorted(stories, key=lambda s: (-counts.get(s, 0), rank[s])):
        k = min(range(n), key=lambda i: (loads[i], i))
        shards[k].append(s)
        loads[k] += counts.get(s, 0)
    return [sorted(sh, key=rank.__getitem__) for sh in shards]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("stories")
    s1.add_argument("shard_id", type=int)
    s1.add_argument("n_shards", type=int)
    s2 = sub.add_parser("plan")
    s2.add_argument("n_shards", type=int)
    a = ap.parse_args(argv)
    counts = chunk_counts()
    shards = plan_shards(priority_stories(), counts, a.n_shards)
    if a.cmd == "stories":
        if not 0 <= a.shard_id < a.n_shards:
            print(f"shard-id must be in 0..{a.n_shards - 1}", file=sys.stderr)
            return 2
        print("\n".join(shards[a.shard_id]))
        return 0
    for k, sh in enumerate(shards):
        print(f"shard {k}: {sum(counts[s] for s in sh)} chunks, {len(sh)} stories")
        for s in sh:
            print(f"  {s} ({counts[s]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
