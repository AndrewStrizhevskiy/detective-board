#!/usr/bin/env python3
"""Entity-answer switch off vs on: paired tables from saved eval/pre_reveal.py result files.

    uv run python eval/entity_compare.py --off OFF.json[,OFF2.json] --on ON.json[,ON2.json] \
        [--condition full] [--ids a,b] [--title TEXT]

Rows are matched on (id, condition). Metrics per arm (n = rows, Wilson 95 % intervals):
  culprit named      the scorer of eval/pre_reveal.py (alias of the culprit in the answer or its quotes)
  refused            status refused
  answered, not named
  innocent accused   the scorer's proxy: a cleared person's name, no culprit alias
  culprit named, strict  lexical 'named' AND the entity line (if any) does not name somebody else:
                     the quote may hold the culprit while the line names the innocent
  entity line names a cleared person   'The text names <Name> here.' with a Name from cleared_names
  wrong person named the entity answer's own line 'The text names <Name> here.' with a <Name> that
                     matches no culprit alias (any person, not only the cleared ones)
and the paired counts (only off / only on) with the exact McNemar p. No model call.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "eval",):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import metrics as M  # noqa: E402

NAMES_LINE = re.compile(r"The text names (.+?) here\.")


def load(paths: str, condition: str | None) -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    rows: dict[tuple[str, str], dict] = {}
    cases: dict[str, dict] = {}
    for p in [x for x in paths.split(",") if x]:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        cases.update(d["cases"])
        for r in d["rows"]:
            if condition and r["condition"] != condition:
                continue
            rows[(r["id"], r["condition"])] = r
    return rows, cases


def named_person(row: dict) -> str | None:
    m = NAMES_LINE.search(row.get("answer") or "")
    return m.group(1) if m else None


def wrong_person(row: dict, case: dict) -> bool:
    """The answer names a person (entity line) who is none of the culprit's aliases."""
    who = named_person(row)
    if who is None:
        return False
    for alias_set in case["culprit_names"]:
        if all(re.search(r"(?<![A-Za-z])" + re.escape(a), who, re.I) for a in alias_set):
            return False
    return True


def line_names_cleared(row: dict, case: dict) -> bool:
    """The entity line names a cleared person (cleared_names of the case): an accusation of the
    innocent even when the culprit's name stands in the quote next to it."""
    who = named_person(row)
    return who is not None and any(
        re.search(r"(?<![A-Za-z])" + re.escape(n), who, re.I) for n in case.get("cleared_names", [])
    )


def flags(row: dict, case: dict) -> dict[str, bool]:
    wp = wrong_person(row, case)
    return {
        "named": row["outcome"] == "named",
        "named_strict": row["outcome"] == "named" and not wp,
        "innocent_line": line_names_cleared(row, case),
        "refused": row["outcome"] == "refused",
        "wrong": row["outcome"] == "wrong",
        "innocent": bool(row.get("innocent_accused")),
        "wrong_person": wp,
        "not_a_person": "points here to a cause that is not a person" in (row.get("answer") or ""),
    }


def pct(s: dict) -> str:
    if s["value"] is None:
        return "n/a"
    lo, hi = s["ci95"]
    return f"{s['k']}/{s['n']} = {100 * s['value']:.0f} % [{100 * lo:.0f}, {100 * hi:.0f}]"


def compare(off: dict, on: dict, cases: dict[str, dict], ids: set[str] | None = None) -> dict:
    keys = sorted(k for k in off if k in on and (ids is None or k[0] in ids))
    fo = {k: flags(off[k], cases[k[0]]) for k in keys}
    fn = {k: flags(on[k], cases[k[0]]) for k in keys}
    n = len(keys)
    arms: dict[str, Any] = {}
    for label, f in (("off", fo), ("on", fn)):
        arms[label] = {
            "n": n,
            **{
                m: M.share(sum(f[k][m] for k in keys), n)
                for m in (
                    "named",
                    "named_strict",
                    "refused",
                    "wrong",
                    "innocent",
                    "innocent_line",
                    "wrong_person",
                    "not_a_person",
                )
            },
        }
    paired = {
        m: M.paired({str(k): fo[k][m] for k in keys}, {str(k): fn[k][m] for k in keys})
        for m in ("named", "named_strict", "innocent", "innocent_line", "refused", "wrong_person")
    }
    return {"keys": keys, "arms": arms, "paired": paired, "off": fo, "on": fn}


def render(res: dict, off: dict, on: dict, title: str) -> str:
    a, n = res["arms"], res["arms"]["off"]["n"]
    L = [f"### {title}", "", f"n = {n} questions (Wilson 95 % intervals)", ""]
    L += [
        "| arm | culprit named (lexical) | **culprit named, strict** | refused | answered, not named "
        "| innocent accused (proxy) | entity line names a cleared person | wrong person named "
        "| NOT_A_PERSON answers |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for label in ("off", "on"):
        x = a[label]
        L.append(
            f"| switch {label} | {pct(x['named'])} | {pct(x['named_strict'])} | {pct(x['refused'])} "
            f"| {pct(x['wrong'])} | {pct(x['innocent'])} | {pct(x['innocent_line'])} "
            f"| {pct(x['wrong_person'])} | {pct(x['not_a_person'])} |"
        )
    L.append("")
    for m, label in (
        ("named", "culprit named (lexical)"),
        ("named_strict", "culprit named, strict"),
        ("innocent", "innocent accused (proxy)"),
        ("innocent_line", "entity line names a cleared person"),
        ("refused", "refused"),
        ("wrong_person", "wrong person named"),
    ):
        p = res["paired"][m]
        L.append(
            f"- paired, {label}: only off {p['only_a']}, only on {p['only_b']}, "
            f"exact McNemar p {p['p_mcnemar']:.3g} (n {p['n']})"
        )
    L += [
        "",
        "| id | cond | off | on | on strategy | on answer (clipped) |",
        "|---|---|---|---|---|---|",
    ]
    for k in res["keys"]:
        o, w = off[k], on[k]
        ans = " ".join((w.get("answer") or "").split())
        ans = (ans[:200] + "…") if len(ans) > 200 else ans
        L.append(
            f"| {k[0]} | {k[1]} | {o['outcome']} | {w['outcome']}"
            f"{' (innocent)' if w.get('innocent_accused') else ''}"
            f"{' (wrong person)' if res['on'][k]['wrong_person'] else ''} | "
            f"{(w.get('strategy') or '-')[:48]} | {ans.replace('|', '/')} |"
        )
    return "\n".join(L) + "\n"


def unchanged(off: dict, on: dict) -> list[str]:
    """Ids whose ON row did not run the entity mode and whose answer equals the OFF answer."""
    return sorted(
        k[0]
        for k in off
        if k in on
        and "entity choice" not in (on[k].get("strategy") or "")
        and off[k].get("answer") == on[k].get("answer")
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--off", required=True)
    ap.add_argument("--on", required=True)
    ap.add_argument("--condition", default="")
    ap.add_argument("--ids", default="")
    ap.add_argument("--title", default="Switch off vs on")
    args = ap.parse_args(argv)
    cond = args.condition or None
    off, c1 = load(args.off, cond)
    on, c2 = load(args.on, cond)
    cases = {**c1, **c2}
    ids = {x for x in args.ids.split(",") if x} or None
    res = compare(off, on, cases, ids)
    print(render(res, off, on, args.title))
    print(
        "rows whose answer is identical with the switch on (entity mode did not run):",
        unchanged(off, on),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
