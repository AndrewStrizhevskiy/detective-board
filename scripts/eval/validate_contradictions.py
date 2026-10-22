#!/usr/bin/env python3
"""Validate eval/golden/contradictions.jsonl (stdlib only).

Checks: JSON per line, required fields and types, unique ids, known kinds,
expected_finding consistent with kind (controls false, others true), every
involved_claims quote is a verbatim substring of data/clean/<story>.txt after
whitespace normalisation, positives cite >= 2 quotes, and minimum counts per kind.

Usage: python3 scripts/eval/validate_contradictions.py [contradictions.jsonl] [clean_dir]
Exit code 0 = valid, 1 = problems found.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KINDS = {
    "R1_place_conflict",
    "R2_order_cycle_or_inconsistency",
    "R3_claim_vs_fact",
    "consistent_control",
}
STRENGTHS = {"explicit", "inferred"}
MIN_TOTAL = 24
# R1 minimum is 4, not 5: the corpus has only one textbook person-in-two-places
# case (wisteria-lodge); the other three R1 items are borderline and flagged so.
MIN_COUNTS = {
    "R1_place_conflict": 4,
    "R2_order_cycle_or_inconsistency": 3,
    "R3_claim_vs_fact": 8,
    "consistent_control": 8,
}
FIELDS = {
    "id": str,
    "story": str,
    "kind": str,
    "question": str,
    "expected_finding": bool,
    "expected_description": str,
    "involved_claims": list,
    "evidence_strength": str,
    "needs_time_normalisation": bool,
    "notes": str,
}
MIN_QUOTE_CHARS = 12


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    qpath = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval/golden/contradictions.jsonl"
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
        kind = it.get("kind")
        if kind not in KINDS:
            errors.append(f"{tag}: unknown kind {kind!r}")
        if it.get("evidence_strength") not in STRENGTHS:
            errors.append(f"{tag}: evidence_strength must be one of {sorted(STRENGTHS)}")
        story = it.get("story")
        if story not in corpus:
            errors.append(f"{tag}: unknown story {story!r}")
        for f in ("question", "expected_description"):
            if isinstance(it.get(f), str) and not it[f].strip():
                errors.append(f"{tag}: empty {f}")
        if isinstance(it.get("expected_finding"), bool) and kind in KINDS:
            want = kind != "consistent_control"
            if it["expected_finding"] is not want:
                errors.append(f"{tag}: kind {kind} requires expected_finding={want}")
        claims = it.get("involved_claims") if isinstance(it.get("involved_claims"), list) else []
        need = 2
        if len(claims) < need:
            errors.append(f"{tag}: needs >= {need} involved_claims, has {len(claims)}")
        seen = set()
        for k, c in enumerate(claims):
            quotes_total += 1
            if not (
                isinstance(c, dict)
                and all(
                    isinstance(c.get(x), str) and c.get(x).strip() for x in ("who", "what", "quote")
                )
            ):
                errors.append(
                    f"{tag}: involved_claims[{k}] must be {{who, what, quote}} non-empty strings"
                )
                continue
            quote = norm(c["quote"])
            if len(quote) < MIN_QUOTE_CHARS:
                errors.append(f"{tag}: involved_claims[{k}] quote too short")
            if quote in seen:
                errors.append(f"{tag}: involved_claims[{k}] duplicate quote")
            seen.add(quote)
            if story in corpus:
                cnt = corpus[story].count(quote)
                if cnt == 0:
                    errors.append(
                        f"{tag}: involved_claims[{k}] NOT FOUND in {story}: {quote[:80]!r}"
                    )
                else:
                    quotes_ok += 1

    counts = Counter(it.get("kind") for _, it in items)
    if len(items) < MIN_TOTAL:
        errors.append(f"only {len(items)} items, need >= {MIN_TOTAL}")
    for k, m in MIN_COUNTS.items():
        if counts.get(k, 0) < m:
            errors.append(f"kind {k}: {counts.get(k, 0)} < {m}")

    print(f"items: {len(items)}, unique ids: {len(ids)}")
    print("per kind: " + ", ".join(f"{k}={counts.get(k, 0)}" for k in sorted(KINDS)))
    print(f"quotes verified: {quotes_ok}/{quotes_total}")
    pos = sum(1 for _, it in items if it.get("expected_finding") is True)
    tn = sum(1 for _, it in items if it.get("needs_time_normalisation") is True)
    inferred = sum(1 for _, it in items if it.get("evidence_strength") == "inferred")
    print(
        f"positives: {pos}, controls: {len(items) - pos}, needs_time_normalisation: {tn}, inferred: {inferred}"
    )
    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
