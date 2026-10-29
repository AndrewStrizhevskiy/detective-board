#!/usr/bin/env python3
"""Apply human review verdicts (issue #9) to the gold sets. Stdlib only.

Usage: python3 scripts/eval/apply_review.py eval/review/<date>/verdicts.csv [--status] [--dry-run]
Checks the CSV filled from the review kit (scripts/eval/review_kit.py): a GitHub login in
`reviewer`, an ISO `date`, a verdict of ok | fixed | drop | unsure, and a `fix` text for every
verdict but ok. Every golden question or contradiction case marked ok or fixed gets
`reviewed_by` / `reviewed_on` in its JSONL line. An extraction chunk gets them in its file once
every claim and relation row of it is ok or fixed, with `reviewed_scope: ["claims", "relations"]`:
its entities and events were not in the kit and stay unreviewed. Other lines and files stay byte
for byte the same. `drop` and `unsure` are listed, never applied: removing an item or changing
its category or kind can move items between dev and test (split.json) and is the eval-engineer's
call. Marks are only added, never removed: take one back by hand. An id the files do not have
stops the run. --status prints the counts for docs/DISCLOSURE.md and writes nothing.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETS = {
    "golden": ROOT / "eval" / "golden" / "questions.jsonl",
    "contradictions": ROOT / "eval" / "golden" / "contradictions.jsonl",
}
EXTRACTION = ROOT / "eval" / "extraction_gold"
VERDICTS = ("ok", "fixed", "drop", "unsure")
APPLIED = ("ok", "fixed")
CHUNK_SCOPE = ["claims", "relations"]  # what the kit shows of a chunk
HEADER = ["item_id", "set", "assignee", "reviewer", "date", "verdict", "fix", "time_min"]
# the same rules as extract/curated_schema.check_review (#22)
_LOGIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")


def _is_date(s: str) -> bool:
    try:
        return len(s) == 10 and dt.date.fromisoformat(s).isoformat() == s
    except ValueError:
        return False


def read_rows(path: Path) -> tuple[list[dict], list[str]]:
    """Rows of the CSV and the problems found in the filled ones (empty verdict = not reviewed)."""
    # utf-8-sig: a spreadsheet may save the file with a byte-order mark
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []
    if header != HEADER:
        return rows, [
            f"header must be {','.join(HEADER)} (comma-separated); got {','.join(header)}"
        ]
    problems = []
    seen = set()
    for n, r in enumerate(rows, 2):
        tag = f"line {n} [{r.get('item_id')}]"
        if r.get("item_id") in seen:
            problems.append(f"{tag}: duplicate item_id")
        seen.add(r.get("item_id"))
        v = (r.get("verdict") or "").strip()
        if not v:
            if any((r.get(k) or "").strip() for k in ("reviewer", "date", "fix", "time_min")):
                problems.append(f"{tag}: filled in but no verdict")
            continue
        if v not in VERDICTS:
            problems.append(f"{tag}: verdict must be one of {', '.join(VERDICTS)}")
        if not _LOGIN.match((r.get("reviewer") or "").strip()):
            problems.append(f"{tag}: reviewer must be a GitHub login")
        if not _is_date((r.get("date") or "").strip()):
            problems.append(f"{tag}: date must be a real date, YYYY-MM-DD")
        if v != "ok" and not (r.get("fix") or "").strip():
            problems.append(f"{tag}: verdict {v} needs a fix text")
        if (r.get("time_min") or "").strip() and not re.fullmatch(
            r"\d+(\.\d+)?", r["time_min"].strip()
        ):
            problems.append(f"{tag}: time_min must be a number of minutes")
    return rows, problems


def review_of(rows: list[dict]) -> dict[str, tuple[str, str]]:
    return {
        r["item_id"]: (r["reviewer"].strip(), r["date"].strip())
        for r in rows
        if (r.get("verdict") or "").strip() in APPLIED
    }


def apply_jsonl(path: Path, reviews: dict[str, tuple[str, str]], write: bool) -> int:
    """Set reviewed_by / reviewed_on on the reviewed lines; returns how many lines changed.
    Raises SystemExit when a reviewed id is not in the file (renamed or removed)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    have = {json.loads(line).get("id") for line in lines if line.strip()}
    missing = sorted(set(reviews) - have)
    if missing:
        raise SystemExit(f"FAIL {path.name} has no item {', '.join(missing)}; nothing written")
    changed = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("id") not in reviews:
            continue
        by, on = reviews[item["id"]]
        if item.get("reviewed_by") == by and item.get("reviewed_on") == on:
            continue
        item["reviewed_by"], item["reviewed_on"] = by, on
        lines[i] = json.dumps(item, ensure_ascii=False)
        changed += 1
    if write and changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def apply_extraction(rows: list[dict], write: bool) -> tuple[int, list[str]]:
    """A chunk counts as reviewed when all its rows are ok or fixed; returns (changed, pending)."""
    per_chunk: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("set") == "extraction":
            per_chunk[r["item_id"].split(":")[1]].append(r)
    changed, pending = 0, []
    for chunk_id, rs in sorted(per_chunk.items()):
        if not all((r.get("verdict") or "").strip() in APPLIED for r in rs):
            pending.append(chunk_id)
            continue
        who = sorted({r["reviewer"].strip() for r in rs})
        if len(who) != 1:
            raise SystemExit(
                f"FAIL {chunk_id}: one chunk, one reviewer (the kit assigns it whole); got {', '.join(who)}"
            )
        by, on = who[0], max(r["date"].strip() for r in rs)
        path = EXTRACTION / f"{chunk_id}.json"
        if not path.exists():
            raise SystemExit(f"FAIL no extraction gold file {path.name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("reviewed_by"), data.get("reviewed_on"), data.get("reviewed_scope")) == (
            by,
            on,
            CHUNK_SCOPE,
        ):
            continue
        data["reviewed_by"], data["reviewed_on"], data["reviewed_scope"] = by, on, CHUNK_SCOPE
        changed += 1
        if write:
            # the files' own format: indent 1, no newline at the end
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return changed, pending


def status(rows: list[dict]) -> list[str]:
    """One line per set for the review table of docs/DISCLOSURE.md."""
    out = []
    for kind in ("golden", "contradictions", "extraction"):
        rs = [r for r in rows if r.get("set") == kind]
        done = [r for r in rs if (r.get("verdict") or "").strip()]
        counts = {v: sum((r.get("verdict") or "").strip() == v for r in done) for v in VERDICTS}
        who = ", ".join(sorted({r["reviewer"].strip() for r in done})) or "-"
        when = ", ".join(sorted({r["date"].strip() for r in done})) or "-"
        mins = sum(float(r["time_min"]) for r in done if (r.get("time_min") or "").strip())
        out.append(
            f"{kind}: {len(done)} of {len(rs)} rows reviewed by {who} on {when}; "
            f"ok {counts['ok']}, fixed {counts['fixed']}, drop {counts['drop']}, unsure {counts['unsure']}; "
            f"{mins:.0f} min"
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("csv", help="eval/review/<date>/verdicts.csv")
    ap.add_argument("--status", action="store_true", help="print the counts only, write nothing")
    ap.add_argument("--dry-run", action="store_true", help="say what would change, write nothing")
    args = ap.parse_args(argv)
    rows, problems = read_rows(Path(args.csv))
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return 1
    if args.status:
        print("\n".join(status(rows)))
        return 0
    write = not args.dry_run
    reviews = review_of(rows)
    for kind, path in SETS.items():  # every id check before anything is written
        ids = {r["item_id"] for r in rows if r.get("set") == kind}
        apply_jsonl(path, {k: v for k, v in reviews.items() if k in ids}, False)
    apply_extraction(rows, False)
    for kind, path in SETS.items():
        ids = {r["item_id"] for r in rows if r.get("set") == kind}
        n = apply_jsonl(path, {k: v for k, v in reviews.items() if k in ids}, write)
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"{shown}: {n} items {'marked' if write else 'would be marked'} reviewed")
    n, pending = apply_extraction(rows, write)
    print(
        f"eval/extraction_gold: {n} chunks {'marked' if write else 'would be marked'} reviewed; not complete yet: {', '.join(pending) or 'none'}"
    )
    for r in rows:
        v = (r.get("verdict") or "").strip()
        if v in ("drop", "unsure"):
            print(f"{v.upper()} {r['item_id']}: {r['fix']}  (not applied; for the eval-engineer)")
    print("\n".join(status(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
