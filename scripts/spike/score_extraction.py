#!/usr/bin/env python3
"""Score extraction predictions against labelled gold (eval/extraction_gold/).

Predictions: JSONL, one object per line: {"chunk_id": str, "output": <raw model string>}
or {"chunk_id": str, "extraction": <dict>}. Invalid/missing outputs count as empty
(they hurt recall) and lower the JSON-validity rate.

Usage: score_extraction.py PREDICTIONS.jsonl [--gold eval/extraction_gold] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from detective_board.extract.schema import Extraction  # noqa: E402

TITLES = {
    "mr",
    "mrs",
    "miss",
    "dr",
    "sir",
    "colonel",
    "inspector",
    "the",
    "a",
    "an",
    "old",
    "young",
}
MATCH_THRESHOLD = 0.5


def norm(s: str | None) -> str:
    s = (s or "").lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"'s\b", "", s)
    toks = [t for t in re.findall(r"[a-z0-9]+", s) if t not in TITLES]
    return " ".join(toks)


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower().replace("’", "'"))


def token_f1(a: str, b: str) -> float:
    ta, tb = Counter(tokens(a)), Counter(tokens(b))
    common = sum((ta & tb).values())
    if not common:
        return 0.0
    p, r = common / sum(ta.values()), common / sum(tb.values())
    return 2 * p * r / (p + r)


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def quote_grounded(quote: str, chunk: str) -> bool:
    q = collapse_ws(quote)
    return bool(q) and q in collapse_ws(chunk)


def parse_prediction(rec: dict) -> Extraction | None:
    """Return a validated Extraction or None if the record is not valid."""
    try:
        data = rec["extraction"] if "extraction" in rec else json.loads(rec["output"])
        return Extraction.model_validate(data)
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def _names(e) -> set[str]:
    return {n for n in (norm(e.name), *(norm(a) for a in e.aliases)) if n}


def match_entities(pred, gold) -> int:
    """Greedy one-to-one matching; names/aliases are normalized and any overlap matches."""
    used: set[int] = set()
    tp = 0
    for p in pred:
        pn = _names(p)
        for i, g in enumerate(gold):
            if i not in used and pn & _names(g):
                used.add(i)
                tp += 1
                break
    return tp


def alias_map(gold_entities) -> dict[str, str]:
    m: dict[str, str] = {}
    for g in gold_entities:
        for n in _names(g):
            m.setdefault(n, norm(g.name))
    return m


def _canon(name: str, amap: dict[str, str]) -> str:
    n = norm(name)
    return amap.get(n, n)


def match_quoted(pred, gold, key, amap, threshold=MATCH_THRESHOLD) -> int:
    """Match items by canonical key(item) equality and quote token-F1 >= threshold."""
    cand = []
    for pi, p in enumerate(pred):
        for gi, g in enumerate(gold):
            if _canon(key(p), amap) == _canon(key(g), amap):
                f = token_f1(p.quote, g.quote)
                if f >= threshold:
                    cand.append((f, pi, gi))
    cand.sort(reverse=True)
    up: set[int] = set()
    ug: set[int] = set()
    for _, pi, gi in cand:
        if pi not in up and gi not in ug:
            up.add(pi)
            ug.add(gi)
    return len(up)


def prf(tp: int, n_pred: int, n_gold: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "n_pred": n_pred, "n_gold": n_gold, "precision": p, "recall": r, "f1": f}


def load_gold(gold_dir: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(gold_dir.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["chunk_id"]] = {"text": d["text"], "gold": Extraction.model_validate(d["gold"])}
    return out


def load_predictions(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["chunk_id"]] = rec
    return out


def score(gold: dict[str, dict], preds: dict[str, dict]) -> dict:
    n_chunks = len(gold)
    valid = 0
    tp = Counter()
    npred = Counter()
    ngold = Counter()
    q_total = q_ok = 0
    for cid, g in gold.items():
        gx: Extraction = g["gold"]
        rec = preds.get(cid)
        px = parse_prediction(rec) if rec else None
        ngold["entities"] += len(gx.entities)
        ngold["claims"] += len(gx.claims)
        ngold["relations"] += len(gx.relations)
        if px is None:
            continue
        valid += 1
        amap = alias_map(gx.entities)
        npred["entities"] += len(px.entities)
        npred["claims"] += len(px.claims)
        npred["relations"] += len(px.relations)
        tp["entities"] += match_entities(px.entities, gx.entities)
        tp["claims"] += match_quoted(px.claims, gx.claims, lambda c: c.speaker, amap)
        tp["relations"] += match_quoted(px.relations, gx.relations, lambda r: r.subject, amap)
        for item in (*px.entities, *px.events, *px.claims, *px.relations):
            q_total += 1
            q_ok += quote_grounded(item.quote, g["text"])
    res = {
        "n_chunks": n_chunks,
        "json_validity_rate": valid / n_chunks if n_chunks else 0.0,
        "quote_grounding_rate": q_ok / q_total if q_total else 0.0,
        "n_quotes": q_total,
    }
    for k in ("entities", "claims", "relations"):
        res[k] = prf(tp[k], npred[k], ngold[k])
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("predictions", type=Path)
    ap.add_argument("--gold", type=Path, default=ROOT / "eval" / "extraction_gold")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    a = ap.parse_args(argv)
    res = score(load_gold(a.gold), load_predictions(a.predictions))
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"chunks: {res['n_chunks']}  json-valid: {res['json_validity_rate']:.1%}")
    print(f"quote grounding: {res['quote_grounding_rate']:.1%} of {res['n_quotes']} quotes")
    for k in ("entities", "claims", "relations"):
        m = res[k]
        print(
            f"{k:10s} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} "
            f"(tp={m['tp']} pred={m['n_pred']} gold={m['n_gold']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
