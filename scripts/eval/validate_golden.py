#!/usr/bin/env python3
"""Validate eval/golden/questions.jsonl (stdlib only).

Checks: JSON per line, required fields and types, unique ids, known categories,
minimum counts, answerable/refusal consistency, and that every gold quote is a
verbatim substring of data/clean/<story>.txt after whitespace normalisation.

Usage: python3 scripts/eval/validate_golden.py [questions.jsonl] [clean_dir]
Exit code 0 = valid, 1 = problems found.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = {
    "fact",
    "multi-hop",
    "relation",
    "chronology",
    "testimony-contradiction",
    "alibi",
    "cross-story",
    "out-of-corpus",
    "adversarial",
    "language-ru",
}
BEHAVIORS = {"answer", "refuse", "correct_premise", "ignore_injection_and_answer"}
MIN_TOTAL = 45
MIN_COUNTS = {"out-of-corpus": 8, "adversarial": 3, "language-ru": 2}
MAX_COUNTS = {"language-ru": 3}
FIELDS = {
    "id": str,
    "category": str,
    "lang": str,
    "question": str,
    "expected_answer": str,
    "expected_behavior": str,
    "gold_quotes": list,
    "answerable": bool,
    "notes": str,
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    qpath = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval/golden/questions.jsonl"
    cdir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/clean"
    corpus = {p.stem: norm(p.read_text(encoding="utf-8")) for p in sorted(cdir.glob("*.txt"))}
    errors = []
    items = []
    for n, line in enumerate(qpath.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append((n, json.loads(line)))
        except json.JSONDecodeError as e:
            errors.append(f"line {n}: invalid JSON: {e}")

    ids = Counter(it.get("id") for _, it in items)
    for i, c in ids.items():
        if c > 1:
            errors.append(f"duplicate id: {i}")

    quotes_total = quotes_ok = 0
    for n, it in items:
        tag = f"line {n} [{it.get('id')}]"
        for f, t in FIELDS.items():
            if f not in it:
                errors.append(f"{tag}: missing field {f}")
            elif not isinstance(it[f], t):
                errors.append(f"{tag}: field {f} must be {t.__name__}")
        if it.get("category") not in CATEGORIES:
            errors.append(f"{tag}: unknown category {it.get('category')!r}")
        if it.get("expected_behavior") not in BEHAVIORS:
            errors.append(f"{tag}: unknown expected_behavior {it.get('expected_behavior')!r}")
        for f in ("question", "expected_answer"):
            if isinstance(it.get(f), str) and not it[f].strip():
                errors.append(f"{tag}: empty {f}")
        gq = it.get("gold_quotes") if isinstance(it.get("gold_quotes"), list) else []
        if it.get("answerable") is True and not gq:
            errors.append(f"{tag}: answerable but no gold_quotes")
        if it.get("answerable") is False and gq:
            errors.append(f"{tag}: not answerable but has gold_quotes")
        if it.get("category") == "out-of-corpus" and (
            it.get("answerable") is not False or it.get("expected_behavior") != "refuse"
        ):
            errors.append(f"{tag}: out-of-corpus must be answerable=false, behavior=refuse")
        if it.get("expected_behavior") == "refuse" and it.get("answerable") is not False:
            errors.append(f"{tag}: refuse requires answerable=false")
        for k, q in enumerate(gq):
            quotes_total += 1
            if not (
                isinstance(q, dict)
                and isinstance(q.get("story"), str)
                and isinstance(q.get("quote"), str)
            ):
                errors.append(f"{tag}: gold_quotes[{k}] must be {{story, quote}}")
                continue
            story, quote = q["story"], norm(q["quote"])
            if story not in corpus:
                errors.append(f"{tag}: gold_quotes[{k}] unknown story {story!r}")
            elif not quote or quote not in corpus[story]:
                errors.append(f"{tag}: gold_quotes[{k}] NOT FOUND in {story}: {quote[:80]!r}")
            else:
                quotes_ok += 1

    counts = Counter(it.get("category") for _, it in items)
    if len(items) < MIN_TOTAL:
        errors.append(f"only {len(items)} questions, need >= {MIN_TOTAL}")
    for c, m in MIN_COUNTS.items():
        if counts.get(c, 0) < m:
            errors.append(f"category {c}: {counts.get(c, 0)} < {m}")
    for c, m in MAX_COUNTS.items():
        if counts.get(c, 0) > m:
            errors.append(f"category {c}: {counts.get(c, 0)} > {m}")

    print(f"questions: {len(items)}, unique ids: {len(ids)}")
    print("per category: " + ", ".join(f"{c}={counts.get(c, 0)}" for c in sorted(CATEGORIES)))
    print(f"gold quotes verified: {quotes_ok}/{quotes_total}")
    answerable = sum(1 for _, it in items if it.get("answerable") is True)
    print(f"answerable: {answerable}, unanswerable: {len(items) - answerable}")
    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
