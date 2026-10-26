#!/usr/bin/env python3
"""Score the production extraction pipeline (schema v2) against eval/extraction_gold/.

Input: the JSONL written by `python -m detective_board.extract.run --out FILE` (one ChunkResult
per line, see extract/pipeline.py). Items are projected to schema v1 with `schema_v2.to_v1` and
scored by the existing logic in score_extraction.py (strict P/R/F1, quote grounding) and
overlap_metric.py (span overlap). On top: fill rates of the v2-only optional fields and seconds
per chunk. A chunk with status `failed`/`error` counts as invalid (empty prediction).

Usage: score_pipeline.py OUT.jsonl [OUT2.jsonl ...] [--gold DIR] [--json] [--markdown FILE]
Several files print one comparison table (label = file stem).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import overlap_metric  # noqa: E402
import score_extraction as se  # noqa: E402

from detective_board.extract import schema_v2  # noqa: E402
from detective_board.extract.pipeline import ChunkResult  # noqa: E402

USABLE = ("ok", "repaired")  # statuses that carry a parsed extraction
KINDS = ("entities", "claims", "relations")


def load_results(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["chunk_id"]] = rec
    return out


def _extraction(rec: dict) -> schema_v2.Extraction | None:
    if rec.get("status") not in USABLE:
        return None
    res = ChunkResult(rec["chunk_id"], rec.get("story", ""), rec["status"])
    res.extraction = rec.get("extraction") or {}
    try:
        return res.to_extraction()
    except ValueError:  # pydantic.ValidationError is a ValueError
        return None


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def fill_rates(exs: list[schema_v2.Extraction]) -> dict[str, float | None]:
    claims = [c for x in exs for c in x.claims]
    events = [e for x in exs for e in x.events]
    return {
        "claim_about_person": _rate(sum(bool(c.about_person) for c in claims), len(claims)),
        "claim_about_place": _rate(sum(bool(c.about_place) for c in claims), len(claims)),
        "claim_about_time_text": _rate(sum(bool(c.about_time_text) for c in claims), len(claims)),
        "claim_polarity_deny": _rate(sum(c.polarity == "deny" for c in claims), len(claims)),
        "event_in_speech": _rate(sum(e.in_speech for e in events), len(events)),
        "event_transit": _rate(sum(e.transit for e in events), len(events)),
    }


def sec_per_chunk(recs: list[dict]) -> float | None:
    """Mean LLM wall time of the original call (cached records keep it) over chunks that have one."""
    ws = [float(r["wall_s"]) for r in recs if float(r.get("wall_s") or 0) > 0]
    return sum(ws) / len(ws) if ws else None


def score_results(
    gold: dict[str, dict], results: dict[str, dict], gold_dir: Path | None = None
) -> dict[str, Any]:
    exs: dict[str, schema_v2.Extraction] = {}
    for cid in gold:
        if (rec := results.get(cid)) and (x := _extraction(rec)):
            exs[cid] = x
    v1_preds = {
        cid: {"chunk_id": cid, "extraction": schema_v2.to_v1(x).model_dump()}
        for cid, x in exs.items()
    }
    res = se.score(gold, v1_preds)
    in_gold = [results[c] for c in gold if c in results]
    res["n_missing"] = sum(c not in results for c in gold)
    res["status_ok_rate"] = _rate(sum(r.get("status") == "ok" for r in in_gold), len(gold)) or 0.0
    res["truncated"] = sum(bool(r.get("truncated")) for r in in_gold)
    res["fill"] = fill_rates(list(exs.values()))
    res["sec_per_chunk"] = sec_per_chunk(in_gold)
    # span-overlap metric: its run() reads {"chunk_id","output": <json string>} lines
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "v1.jsonl"
        p.write_text(
            "".join(
                json.dumps({"chunk_id": c, "output": json.dumps(r["extraction"])}) + "\n"
                for c, r in v1_preds.items()
            ),
            encoding="utf-8",
        )
        res["overlap"] = {
            k: {"precision": v[0], "recall": v[1], "f1": v[2]}
            for k, v in overlap_metric.run(p, gold_dir).items()
        }
    return res


def score_file(path: Path, gold_dir: Path) -> dict[str, Any]:
    return score_results(se.load_gold(gold_dir), load_results(path), gold_dir)


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def _f(x: float | None, nd: int = 3) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def table(rows: dict[str, dict[str, Any]]) -> list[list[str]]:
    head = ["run", "json ok", "usable", "grounded", "s/chunk"]
    for k in KINDS:
        head += [f"{k[:3]} P", "R", "F1"]
    head += ["ovl clm F1", "ovl rel F1", "person", "place", "time", "deny", "in_speech", "transit"]
    out = [head]
    for label, r in rows.items():
        line = [
            label, _pct(r["status_ok_rate"]), _pct(r["json_validity_rate"]),
            _pct(r["quote_grounding_rate"]), _f(r["sec_per_chunk"], 1),
        ]  # fmt: skip
        for k in KINDS:
            line += [_f(r[k]["precision"]), _f(r[k]["recall"]), _f(r[k]["f1"])]
        fl = r["fill"]
        line += [_f(r["overlap"]["claims"]["f1"], 2), _f(r["overlap"]["relations"]["f1"], 2)]
        line += [_pct(fl[k]) for k in (
            "claim_about_person", "claim_about_place", "claim_about_time_text",
            "claim_polarity_deny", "event_in_speech", "event_transit",
        )]  # fmt: skip
        out.append(line)
    return out


def format_text(rows: dict[str, dict[str, Any]]) -> str:
    t = table(rows)
    w = [max(len(r[i]) for r in t) for i in range(len(t[0]))]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(r)) for r in t)


def format_markdown(rows: dict[str, dict[str, Any]]) -> str:
    t = table(rows)
    lines = ["| " + " | ".join(t[0]) + " |", "|" + "---|" * len(t[0])]
    lines += ["| " + " | ".join(r) + " |" for r in t[1:]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("outputs", type=Path, nargs="+", help="JSONL from extract.run --out")
    ap.add_argument("--gold", type=Path, default=ROOT / "eval" / "extraction_gold")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    ap.add_argument("--markdown", type=Path, help="also write the comparison table here")
    a = ap.parse_args(argv)
    gold = se.load_gold(a.gold)
    rows = {p.stem: score_results(gold, load_results(p), a.gold) for p in a.outputs}
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        print(format_text(rows))
        print(
            "json ok = status ok; usable = ok or repaired; deny/person/place/time = share of "
            "claims; in_speech/transit = share of events"
        )
    if a.markdown:
        a.markdown.parent.mkdir(parents=True, exist_ok=True)
        a.markdown.write_text(format_markdown(rows) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
