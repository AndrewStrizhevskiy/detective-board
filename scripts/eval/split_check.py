#!/usr/bin/env python3
"""Verify eval/golden/split.json against the golden files (stdlib only, no models).

Checks: every id is in exactly one of dev/test, no unknown ids, the 12 answer-check
questions are dev, the recorded rule reproduces the test lists, and the sha256 matches.
`--write` regenerates the file (only before the split is frozen).
Exit code 1 on any problem.
"""

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "eval/golden"
SPLIT = GOLD / "split.json"
SEED = "detective-board-split-v1"
FORCED_DEV = [
    "g001",
    "g007",
    "g028",
    "g032",
    "g016",
    "g019",
    "g022",
    "g038",
    "g047",
    "g056",
    "g057",
    "g062",
]
# test items per stratum (stratum = category for questions, kind for contradiction cases)
Q_TEST = {
    "fact": 4,
    "multi-hop": 3,
    "relation": 2,
    "chronology": 3,
    "testimony-contradiction": 3,
    "alibi": 3,
    "cross-story": 3,
    "out-of-corpus": 5,
    "adversarial": 3,
    "language-ru": 1,
}
C_TEST = {
    "R1_place_conflict": 2,
    "R2_order_cycle_or_inconsistency": 1,
    "R3_claim_vs_fact": 9,
    "consistent_control": 8,
}
RULE = (
    "Deterministic stratified choice. Per stratum (question category / contradiction kind), "
    "candidates are the ids not forced into dev; each is ranked by sha256(seed + ':' + id) "
    "ascending; the first N form the test split (N from test_per_stratum); everything else is dev. "
    "The 12 SELECTION questions of eval/run_answer_check.py are forced into dev because they "
    "already drove prompt fixes."
)


def load(name):
    return [
        json.loads(x) for x in (GOLD / name).read_text(encoding="utf-8").splitlines() if x.strip()
    ]


def rank(i):
    return hashlib.sha256(f"{SEED}:{i}".encode()).hexdigest()


def choose(items, key, quota, forced):
    by = defaultdict(list)
    for it in items:
        by[it[key]].append(it["id"])
    test = []
    for s, n in quota.items():
        cand = sorted((i for i in by[s] if i not in forced), key=rank)
        test += cand[:n]
    test = sorted(test)
    dev = sorted(i["id"] for i in items if i["id"] not in test)
    return dev, test


def digest(content):
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build():
    q, c = load("questions.jsonl"), load("contradictions.jsonl")
    qd, qt = choose(q, "category", Q_TEST, set(FORCED_DEV))
    cd, ct = choose(c, "kind", C_TEST, set())
    content = {"golden": {"dev": qd, "test": qt}, "contradictions": {"dev": cd, "test": ct}}
    return {
        "header": {
            "rule": RULE,
            "seed": SEED,
            "forced_dev": FORCED_DEV,
            "test_per_stratum": {"golden": Q_TEST, "contradictions": C_TEST},
            "sha256_of_content": digest(content),
            "sha256_note": "sha256 of json.dumps(content, sort_keys=True, separators=(',',':'))",
        },
        "content": content,
    }


def main():
    if "--write" in sys.argv:
        SPLIT.write_text(json.dumps(build(), indent=1) + "\n", encoding="utf-8")
    s = json.loads(SPLIT.read_text(encoding="utf-8"))
    q, c = load("questions.jsonl"), load("contradictions.jsonl")
    errs = []
    for name, items, key in (("golden", q, "category"), ("contradictions", c, "kind")):
        part = s["content"][name]
        ids = {i["id"] for i in items}
        d, t = set(part["dev"]), set(part["test"])
        if d & t:
            errs.append(f"{name}: ids in both splits: {sorted(d & t)}")
        if (d | t) != ids or len(part["dev"]) + len(part["test"]) != len(ids):
            errs.append(f"{name}: split does not cover exactly the {len(ids)} ids")
        cat = {i["id"]: i[key] for i in items}
        print(f"{name}: dev {len(d)}, test {len(t)}")
        cnt = Counter((cat[i], "dev" if i in d else "test") for i in ids if i in cat)
        for k in sorted({k for k, _ in cnt}):
            print(f"  {k:36s} dev {cnt[(k, 'dev')]:2d}  test {cnt[(k, 'test')]:2d}")
    if not set(FORCED_DEV) <= set(s["content"]["golden"]["dev"]):
        errs.append("answer-check questions are not all dev")
    if s["header"]["sha256_of_content"] != digest(s["content"]):
        errs.append("sha256 mismatch")
    if build()["content"] != s["content"]:
        errs.append("content does not match the recorded rule")
    for e in errs:
        print("ERROR:", e)
    print("OK" if not errs else "FAILED", "sha256", s["header"]["sha256_of_content"])
    return 1 if errs else 0


sys.exit(main())
