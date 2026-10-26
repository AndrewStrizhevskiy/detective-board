#!/usr/bin/env python3
"""Secondary, span-based extraction metric: a predicted claim/relation counts as a hit when its
quote overlaps (in the chunk text) the quote of some gold item of the same kind. Ignores speaker
and wording, so it measures 'did the model find the right passage', not 'did it label it the same'."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ws = lambda s: re.sub(
    r"\s+", " ", s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
).strip()


def span(text, q):
    i = text.find(ws(q))
    return (i, i + len(ws(q))) if i >= 0 and q.strip() else None


def ov(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def run(pred_path, gold_dir=None):
    preds = {}
    for l in open(pred_path, encoding="utf-8"):
        r = json.loads(l)
        try:
            preds[r["chunk_id"]] = json.loads(r["output"])
        except Exception:
            preds[r["chunk_id"]] = {}
    out = {}
    for kind in ("claims", "relations", "entities", "events"):
        tp_p = n_p = tp_g = n_g = 0
        for f in sorted(
            (Path(gold_dir) if gold_dir else ROOT / "eval/extraction_gold").glob("*.json")
        ):
            g = json.loads(f.read_text(encoding="utf-8"))
            text = ws(g["text"])
            gs = [s for s in (span(text, x["quote"]) for x in g["gold"].get(kind, [])) if s]
            ps = [
                s
                for s in (
                    span(text, x.get("quote", ""))
                    for x in preds.get(g["chunk_id"], {}).get(kind, [])
                )
                if s
            ]
            n_p += len(ps)
            n_g += len(gs)
            tp_p += sum(1 for p in ps if any(ov(p, q) > 0 for q in gs))
            tp_g += sum(1 for q in gs if any(ov(p, q) > 0 for p in ps))
        P = tp_p / n_p if n_p else 0
        R = tp_g / n_g if n_g else 0
        out[kind] = (round(P, 2), round(R, 2), round(2 * P * R / (P + R), 2) if P + R else 0)
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(Path(p).name.split("-2026")[0], run(p))
