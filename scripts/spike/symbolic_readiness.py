#!/usr/bin/env python3
"""How ready is an extraction run for the symbolic layer? Compare prompt versions on the gold chunks.

Input: JSONL(s) from `python -m detective_board.extract.run --out FILE` plus eval/extraction_gold/.
Per run it computes JSON validity, quote grounding, strict and span-overlap F1 (via
score_pipeline), and the field-level rates the symbolic rules depend on:
  events: participants non-empty, participants precision/recall vs gold (events matched by quote
          overlap), time_text / place found in the event's OWN quote, in_speech share;
  claims: polarity=deny share, about_person non-empty, about_person/place/time grounded in the
          claim's own quote/content/speaker;
  speed:  seconds per chunk.
Caveats: gold is AI-labelled, 12 chunks, one run per prompt (temperature 0, seed 42).

Usage: symbolic_readiness.py OUT.jsonl [OUT2.jsonl ...] [--gold DIR] [--stamp S] [--md-dir DIR]
With --stamp the table is also written to <md-dir>/prompt-v2-2-<stamp>.md.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import score_pipeline as sp  # noqa: E402

from detective_board.extract import schema as v1  # noqa: E402
from detective_board.extract import schema_v2  # noqa: E402

OVERLAP_MIN = 0.5  # share of the smaller quote's tokens that must occur in the other quote
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def norm(s: str | None) -> str:
    return " ".join(_PUNCT.sub(" ", (s or "").casefold().replace("’", "'")).split())


def tokens(s: str | None) -> set[str]:
    return set(norm(s).split())


def contains(haystack: str | None, needle: str | None) -> bool:
    """Normalised substring test; an empty needle is not 'contained'."""
    n = norm(needle)
    return bool(n) and f" {n} " in f" {norm(haystack)} "


def quote_overlap(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def same_person(a: str, b: str) -> bool:
    ta, tb = tokens(a), tokens(b)
    return bool(ta and tb) and (ta <= tb or tb <= ta)


def match_events(
    preds: list[schema_v2.Event], golds: list[v1.Event]
) -> list[tuple[schema_v2.Event, v1.Event]]:
    """Greedy one-to-one pairing of predicted and gold events by best quote overlap."""
    cands = sorted(
        (
            (quote_overlap(p.quote, g.quote), i, j)
            for i, p in enumerate(preds)
            for j, g in enumerate(golds)
        ),
        reverse=True,
    )
    used_p: set[int] = set()
    used_g: set[int] = set()
    pairs = []
    for ov, i, j in cands:
        if ov < OVERLAP_MIN:
            break
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        pairs.append((preds[i], golds[j]))
    return pairs


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def _grounded(c: schema_v2.Claim, value: str | None) -> bool:
    return contains(" ".join([c.quote, c.content, c.speaker]), value)


def readiness(gold: dict[str, dict], results: dict[str, dict]) -> dict[str, float | None]:
    events: list[schema_v2.Event] = []
    claims: list[schema_v2.Claim] = []
    pp = pg = ptp = gtp = n_pairs = 0  # participants: predicted, gold, matched (pred / gold side)
    for cid, g in gold.items():
        rec = results.get(cid)
        ex = sp._extraction(rec) if rec else None
        if ex is None:
            continue
        events += ex.events
        claims += ex.claims
        for p, ge in match_events(ex.events, cast("v1.Extraction", g["gold"]).events):
            n_pairs += 1
            gp = ge.participants
            pp += len(p.participants)
            pg += len(gp)
            ptp += sum(any(same_person(x, y) for y in gp) for x in p.participants)
            gtp += sum(any(same_person(x, y) for y in p.participants) for x in gp)
    with_time = [e for e in events if e.time_text]
    with_place = [e for e in events if e.place]
    return {
        "events": float(len(events)),
        "claims": float(len(claims)),
        "ev_participants_nonempty": _rate(sum(bool(e.participants) for e in events), len(events)),
        "ev_participants_P": _rate(ptp, pp),
        "ev_participants_R": _rate(gtp, pg),
        "ev_matched_gold": float(n_pairs),
        "ev_time_filled": _rate(len(with_time), len(events)),
        "ev_time_in_quote": _rate(sum(contains(e.quote, e.time_text) for e in with_time), len(with_time)),
        "ev_place_filled": _rate(len(with_place), len(events)),
        "ev_place_in_quote": _rate(sum(contains(e.quote, e.place) for e in with_place), len(with_place)),
        "ev_in_speech": _rate(sum(e.in_speech for e in events), len(events)),
        "cl_deny": _rate(sum(c.polarity == "deny" for c in claims), len(claims)),
        "cl_about_person": _rate(sum(bool(c.about_person) for c in claims), len(claims)),
        "cl_about_person_grounded": _rate(
            sum(_grounded(c, c.about_person) for c in claims if c.about_person),
            sum(bool(c.about_person) for c in claims),
        ),
        "cl_about_place_grounded": _rate(
            sum(_grounded(c, c.about_place) for c in claims if c.about_place),
            sum(bool(c.about_place) for c in claims),
        ),
        "cl_about_time_grounded": _rate(
            sum(_grounded(c, c.about_time_text) for c in claims if c.about_time_text),
            sum(bool(c.about_time_text) for c in claims),
        ),
    }  # fmt: skip


def score_run(gold: dict[str, dict], results: dict[str, dict], gold_dir: Path | None) -> dict:
    base = sp.score_results(gold, results, gold_dir)
    rd = readiness(gold, results)
    return {
        "json_validity": base["json_validity_rate"],
        "quote_grounding": base["quote_grounding_rate"],
        "truncated": float(base["truncated"]),
        "sec_per_chunk": base["sec_per_chunk"],
        "strict_f1_entities": base["entities"]["f1"],
        "strict_f1_claims": base["claims"]["f1"],
        "strict_f1_relations": base["relations"]["f1"],
        "overlap_f1_claims": base["overlap"]["claims"]["f1"],
        "overlap_f1_relations": base["overlap"]["relations"]["f1"],
        **rd,
    }


# (key, label, kind) kind: pct | num | sec | f
ROWS = [
    ("json_validity", "JSON valid (usable chunks)", "pct"),
    ("quote_grounding", "quote grounding", "pct"),
    ("truncated", "truncated chunks", "num"),
    ("sec_per_chunk", "seconds per chunk", "sec"),
    ("events", "events (count)", "num"),
    ("ev_participants_nonempty", "event participants non-empty", "pct"),
    ("ev_participants_P", "event participants precision vs gold", "pct"),
    ("ev_participants_R", "event participants recall vs gold", "pct"),
    ("ev_matched_gold", "events matched to a gold event", "num"),
    ("ev_time_filled", "event time_text filled", "pct"),
    ("ev_time_in_quote", "event time_text found in own quote", "pct"),
    ("ev_place_filled", "event place filled", "pct"),
    ("ev_place_in_quote", "event place found in own quote", "pct"),
    ("ev_in_speech", "event in_speech share", "pct"),
    ("claims", "claims (count)", "num"),
    ("cl_deny", "claim polarity=deny share", "pct"),
    ("cl_about_person", "claim about_person non-empty", "pct"),
    ("cl_about_person_grounded", "about_person grounded in claim", "pct"),
    ("cl_about_place_grounded", "about_place grounded in claim", "pct"),
    ("cl_about_time_grounded", "about_time grounded in claim", "pct"),
    ("strict_f1_entities", "strict F1 entities", "f"),
    ("strict_f1_claims", "strict F1 claims", "f"),
    ("strict_f1_relations", "strict F1 relations", "f"),
    ("overlap_f1_claims", "span-overlap F1 claims", "f"),
    ("overlap_f1_relations", "span-overlap F1 relations", "f"),
]


def fmt(v: float | None, kind: str) -> str:
    if v is None:
        return "-"
    return {"pct": f"{v:.0%}", "num": f"{v:.0f}", "sec": f"{v:.1f}", "f": f"{v:.3f}"}[kind]


def table(rows: dict[str, dict]) -> list[list[str]]:
    out = [["metric", *rows]]
    for key, label, kind in ROWS:
        out.append([label, *(fmt(r.get(key), kind) for r in rows.values())])
    return out


def format_text(rows: dict[str, dict]) -> str:
    t = table(rows)
    w = [max(len(r[i]) for r in t) for i in range(len(t[0]))]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(r)) for r in t)


def format_markdown(rows: dict[str, dict]) -> str:
    t = table(rows)
    lines = ["| " + " | ".join(t[0]) + " |", "|" + "---|" * len(t[0])]
    lines += ["| " + " | ".join(r) + " |" for r in t[1:]]
    return "\n".join(lines)


CAVEATS = (
    "Caveats: only the 12 gold chunks, one run per prompt (temperature 0, seed 42), so differences "
    "of a few points are noise. Gold is AI-labelled, not human-checked, and not exhaustive "
    "(participants of gold events are often incomplete, so participants precision is a lower "
    "bound). Events are matched to gold events by quote token overlap >= 50% and participants "
    "by name-token containment. 'Found in own quote' is a normalised substring test; "
    "'grounded' for claims also accepts the claim content and speaker. Rates over filled fields "
    "have small denominators."
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("outputs", type=Path, nargs="+")
    ap.add_argument("--gold", type=Path, default=ROOT / "eval" / "extraction_gold")
    ap.add_argument("--stamp", help="write docs/spike/results/prompt-v2-2-<stamp>.md")
    ap.add_argument("--md-dir", type=Path, default=ROOT / "docs" / "spike" / "results")
    a = ap.parse_args(argv)
    gold = sp.se.load_gold(a.gold)
    rows: dict[str, dict[str, Any]] = {
        p.stem: score_run(gold, sp.load_results(p), a.gold) for p in a.outputs
    }
    print(format_text(rows))
    if a.stamp:
        a.md_dir.mkdir(parents=True, exist_ok=True)
        md = a.md_dir / f"prompt-v2-2-{a.stamp}.md"
        md.write_text(
            f"# Prompt v2.1 vs v2.2: symbolic readiness ({a.stamp})\n\n"
            f"{format_markdown(rows)}\n\n{CAVEATS}\n",
            encoding="utf-8",
        )
        print(f"\nwrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
