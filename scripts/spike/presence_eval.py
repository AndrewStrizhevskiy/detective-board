#!/usr/bin/env python3
"""Score the presence pass (extract/presence.py) without any model.

Gold (built here, no LLM; labels are NOT human-reviewed):
  - eval/extraction_gold/*.json events with a named participant, a place and a time_text. A gold item
    is `strict` when person, place and time_text all occur in the event's own quote (what the
    strict grounding can ever produce), else `context` (needs text outside the quote).
  - the quotes of eval/golden/contradictions.jsonl cases c001 (R1, Wisteria), c003 (R1), c038 and
    c043 (controls) with person/place/time written by hand below (CASE_ITEMS); the quote is checked
    to be verbatim in the story's chunks.

Predictions: the `--out` jsonl of `python -m detective_board.extract.presence` (one record per
chunk with `facts`, `n_model_facts`, `grounding`).

Scores per prediction file:
  recall_quote   gold items whose quote is overlapped (>= 50% of the shorter span) by a prediction
  recall_full    ... and person, place and time all agree (folded containment either way; times
                 also by equal clock minutes)
  precision      predictions in chunks that HAVE gold: the share that fully matches a gold item
                 (gold is not exhaustive, so this is a lower bound; `unjudged` = preds elsewhere)
  survival       facts kept / facts the model produced (deterministic grounding drops the rest)
  quote_grounded quote grounded exactly or fuzzily / all model facts, before the other checks

With `stages` in the records (runner with --samples / --verify) the scores are also given per
stage: grounded, voted, verified (precision, recall by quote and full, F1, number of facts).

Usage: scripts/spike/presence_eval.py PRED.jsonl [PRED2.jsonl ...] [--gold-out eval/presence_gold.jsonl]
       [--gold FILE] [--chunks data/chunks.jsonl] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from detective_board.extract.ground import normalise  # noqa: E402
from detective_board.graph.normalize import fold_text, is_unnamed_person, normalize_name  # noqa: E402
from detective_board.graph.timenorm import derive_time_norm  # noqa: E402

# Hand-written person/place/time for quotes of the golden contradiction cases (unreviewed).
CASE_ITEMS: list[dict] = [
    {"case": "c001", "story": "wisteria-lodge", "person": "Garcia", "place": "Wisteria Lodge",
     "time_text": "nearly one o’clock",
     "quote": "He apologised for having disturbed me so late, saying that it was nearly one o’clock."},
    {"case": "c001", "story": "wisteria-lodge", "person": "Garcia", "place": "Oxshott Common",
     "time_text": "since one o’clock", "quote": "He had been there since one o’clock."},
    {"case": "c001", "story": "wisteria-lodge", "person": "Garcia", "place": "Oxshott Common",
     "time_text": "this morning",
     "quote": "He was found dead this morning upon Oxshott Common, nearly a mile from his home."},
    {"case": "c003", "story": "norwood-builder", "person": "McFarlane", "place": "Anerley Arms",
     "time_text": "the night", "quote": "so I spent the night at the Anerley Arms"},
    {"case": "c038", "story": "man-with-the-twisted-lip", "person": "Mrs. St. Clair",
     "place": "Swandam Lane", "time_text": "exactly 4:35",
     "quote": "found herself at exactly 4:35 walking through Swandam Lane on her way back to the station"},
    {"case": "c043", "story": "crooked-man", "person": "Miss Morrison", "place": "Watt Street Mission",
     "time_text": "about a quarter to nine o’clock",
     "quote": "We were returning from the Watt Street Mission about a quarter to nine o’clock."},
]  # fmt: skip

# Strict presence facts read by hand from the extraction-gold chunks (unreviewed; they exist
# because the gold events above give a place that is not in the event's own quote).
HAND_ITEMS: list[dict] = [
    {"case": "hand", "story": "boscombe-valley-mystery", "person": "James McCarthy",
     "place": "Bristol", "time_text": "the morning of last Monday, the 3rd",
     "quote": "Mr. James McCarthy, the only son of the deceased, was then called and gave evidence "
     "as follows: ‘I had been away from home for three days at Bristol, and had only just returned "
     "upon the morning of last Monday, the 3rd."},
    {"case": "hand", "story": "boscombe-valley-mystery", "person": "Charles McCarthy",
     "place": "Hatherley", "time_text": "about three in the afternoon",
     "quote": "On June 3rd, that is, on Monday last, McCarthy left his house at Hatherley about "
     "three in the afternoon and walked down to the Boscombe Pool"},
    {"case": "hand", "story": "boscombe-valley-mystery", "person": "Charles McCarthy",
     "place": "Boscombe Pool", "time_text": "about three in the afternoon",
     "quote": "On June 3rd, that is, on Monday last, McCarthy left his house at Hatherley about "
     "three in the afternoon and walked down to the Boscombe Pool"},
]  # fmt: skip


def load_chunks(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {r["chunk_id"]: r for r in map(json.loads, (ln for ln in f if ln.strip()))}


def _in(text: str, needle: str) -> bool:
    n = fold_text(needle)
    return bool(n) and f" {n} " in f" {fold_text(text)} "


def _present(quote: str, forms: list[str], surname: bool = False) -> bool:
    """A form (or, for persons, its surname) occurs in the quote."""
    keys = [*forms, *(normalize_name(f) for f in forms)]
    if surname:
        keys += [k.split()[-1] for k in keys if len(k.split()) >= 2 and len(k.split()[-1]) >= 3]
    return any(_in(quote, k) for k in keys if k)


def locate(chunks: dict[str, dict], story: str, quote: str) -> str | None:
    q = normalise(quote.strip()).text
    for cid in sorted(chunks):
        if chunks[cid]["story"] == story and q in normalise(chunks[cid]["text"]).text:
            return cid
    return None


def build_gold(chunks: dict[str, dict], gold_dir: Path, contradictions: Path) -> list[dict]:
    items: list[dict] = []
    for f in sorted(glob.glob(str(gold_dir / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        ents = d["gold"].get("entities", [])
        forms = {e["name"]: [e["name"], *e.get("aliases", [])] for e in ents}
        for ev in d["gold"].get("events", []):
            place, time_text, q = ev.get("place"), ev.get("time_text"), ev["quote"]
            if not (place and time_text):
                continue
            for person in ev.get("participants", []):
                if is_unnamed_person(person) or d["chunk_id"] not in chunks:
                    continue
                in_q = {
                    "person": _present(q, forms.get(person, [person]), True),
                    "place": _present(q, forms.get(place, [place])),
                    "time_text": _in(q, time_text),
                }
                items.append(
                    {"source": "extraction_gold", "chunk_id": d["chunk_id"], "story": d["story"],
                     "quote": q, "person": person, "place": place, "time_text": time_text,
                     "person_forms": forms.get(person, [person]),
                     "place_forms": forms.get(place, [place]),
                     "in_quote": in_q, "strict": all(in_q.values())}
                )  # fmt: skip
    cases = {
        json.loads(x)["id"]: json.loads(x) for x in contradictions.read_text().splitlines() if x
    }
    for it in [*CASE_ITEMS, *HAND_ITEMS]:
        case = cases.get(it["case"], {} if it["case"] == "hand" else None)
        cid = locate(chunks, it["story"], it["quote"])
        if case is None or cid is None:
            raise SystemExit(f"{it['case']}: quote not found in the chunks: {it['quote'][:50]}")
        q = it["quote"]
        in_q = {
            "person": _present(q, [it["person"]], True),
            "place": _present(q, [it["place"]]),
            "time_text": _in(q, it["time_text"]),
        }
        items.append(
            {"source": "hand" if it["case"] == "hand" else f"contradiction:{it['case']}",
             "chunk_id": cid, "story": it["story"],
             "quote": q, "person": it["person"], "place": it["place"], "time_text": it["time_text"],
             "person_forms": [it["person"]], "place_forms": [it["place"]], "in_quote": in_q, "strict": all(in_q.values())}
        )  # fmt: skip
    for i, it in enumerate(items):
        it["id"] = f"pg{i:03d}"
    return items


# --------------------------------------------------------------------------- scoring


def _span(chunks: dict[str, dict], chunk_id: str, quote: str) -> tuple[int, int] | None:
    text = normalise(chunks[chunk_id]["text"]).text
    q = normalise(quote.strip()).text
    i = text.find(q) if q else -1
    return (i, i + len(q)) if i >= 0 else None


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    ov = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    return ov >= 0.5 * min(a[1] - a[0], b[1] - b[0])


def _same(a: str, b: str) -> bool:
    fa, fb = (
        fold_text(normalize_name(a)) or fold_text(a),
        fold_text(normalize_name(b)) or fold_text(b),
    )
    return bool(fa and fb) and (f" {fa} " in f" {fb} " or f" {fb} " in f" {fa} ")


def _same_time(a: str, b: str) -> bool:
    if _same(a, b):
        return True
    ta, tb = derive_time_norm(a), derive_time_norm(b)
    return ta.lo is not None and (ta.lo, ta.hi) == (tb.lo, tb.hi) and ta.method == tb.method


def fields_agree(pred: dict, gold: dict) -> bool:
    """Person and place agree with the gold name or any of its aliases (`*_forms`)."""
    return (
        any(_same(pred["person"], f) for f in gold.get("person_forms", [gold["person"]]))
        and any(_same(pred["place"], f) for f in gold.get("place_forms", [gold["place"]]))
        and _same_time(pred["time_text"], gold["time_text"])
    )


def _prf(tp: int, n_pred: int, n_gold: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3),
            "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}  # fmt: skip


def score(gold: list[dict], preds: list[dict], chunks: dict[str, dict]) -> dict:
    """`preds`: presence result records (as written by the runner's --out)."""
    by_chunk: dict[str, list[dict]] = {}
    for r in preds:
        by_chunk[r["chunk_id"]] = r.get("facts", [])
    out: dict = {}
    for tier, subset in (("strict", [g for g in gold if g["strict"]]), ("all", gold)):
        found = full = 0
        matched: set[tuple[str, int]] = set()
        for g in subset:
            gs = _span(chunks, g["chunk_id"], g["quote"])
            hit_q = hit_f = False
            for j, p in enumerate(by_chunk.get(g["chunk_id"], [])):
                ps = _span(chunks, g["chunk_id"], p["quote"])
                if gs and ps and _overlap(gs, ps):
                    hit_q = True
                    if fields_agree(p, g):
                        hit_f = True
                        matched.add((g["chunk_id"], j))
            found += hit_q
            full += hit_f
        gold_chunks = {g["chunk_id"] for g in subset}
        judged = [(c, j) for c in gold_chunks for j in range(len(by_chunk.get(c, [])))]
        out[tier] = {
            "gold": len(subset),
            "recall_quote": round(found / len(subset), 3) if subset else 0.0,
            "recall_full": round(full / len(subset), 3) if subset else 0.0,
            "precision": round(len(matched) / len(judged), 3) if judged else 0.0,
            "f1_full": _prf(len(matched), len(judged), len(subset))["f1"],
            "preds_judged": len(judged),
        }
    model_facts = sum(r.get("n_model_facts", 0) for r in preds)
    kept = sum(len(r.get("facts", [])) for r in preds)
    qn = sum(r.get("grounding", {}).get("none", 0) for r in preds)
    qall = sum(sum(r.get("grounding", {}).values()) for r in preds)
    out["facts_model"], out["facts_kept"] = model_facts, kept
    out["survival"] = round(kept / model_facts, 3) if model_facts else 0.0
    out["quote_grounded"] = round(1 - qn / qall, 3) if qall else 0.0
    out["unjudged_preds"] = kept - out["all"]["preds_judged"]
    out["chunks"] = len(preds)
    out["with_context_fields"] = sum(
        bool(f.get("context")) for r in preds for f in r.get("facts", [])
    )
    return out


STAGES = ("grounded", "voted", "verified")


def score_stages(gold: list[dict], preds: list[dict], chunks: dict[str, dict]) -> dict:
    """Precision/recall after each pipeline stage, from the `stages` of the runner's records:
    grounded (first sample, after deterministic grounding), voted (--samples majority; equal to
    grounded when samples = 1), verified (--verify; equal to voted without it = the final facts).
    Records without `stages` (older runs) give no stages."""
    if not preds or not all("stages" in r for r in preds):
        return {}
    out: dict = {}
    for st in STAGES:
        recs = [{**r, "facts": r["stages"].get(st, [])} for r in preds]
        sc = score(gold, recs, chunks)
        out[st] = {
            t: {
                k: sc[t][k]
                for k in (
                    "precision",
                    "recall_quote",
                    "recall_full",
                    "f1_full",
                    "preds_judged",
                    "gold",
                )
            }
            for t in ("strict", "all")
        }
        out[st]["facts"] = sum(len(r["facts"]) for r in recs)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pred", nargs="*", type=Path, help="presence --out jsonl file(s)")
    ap.add_argument("--chunks", type=Path, default=ROOT / "data" / "chunks.jsonl")
    ap.add_argument("--gold", type=Path, help="use this gold jsonl instead of building it")
    ap.add_argument("--gold-out", type=Path, help="write the built gold here")
    ap.add_argument("--json", type=Path, help="write the scores here")
    a = ap.parse_args(argv)
    chunks = load_chunks(a.chunks)
    if a.gold:
        gold = [json.loads(ln) for ln in a.gold.read_text(encoding="utf-8").splitlines() if ln]
    else:
        gold = build_gold(chunks, ROOT / "eval" / "extraction_gold",
                          ROOT / "eval" / "golden" / "contradictions.jsonl")  # fmt: skip
    if a.gold_out:
        a.gold_out.write_text(
            "".join(json.dumps(g, ensure_ascii=False) + "\n" for g in gold), encoding="utf-8"
        )
    strict = sum(g["strict"] for g in gold)
    print(
        f"gold: {len(gold)} items, {strict} strict (person, place, time all in the quote)",
        file=sys.stderr,
    )
    results: dict[str, dict] = {}
    for path in a.pred:
        recs = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]
        results[str(path)] = score(gold, recs, chunks)
        if stages := score_stages(gold, recs, chunks):
            results[str(path)]["stages"] = stages
    for name, r in results.items():
        s, al = r["strict"], r["all"]
        print(
            f"{name}: strict P={s['precision']} Rq={s['recall_quote']} Rf={s['recall_full']} "
            f"(n={s['gold']}) | all Rq={al['recall_quote']} Rf={al['recall_full']} (n={al['gold']}) "
            f"| survival={r['survival']} quote_grounded={r['quote_grounded']} "
            f"facts={r['facts_kept']}/{r['facts_model']}",
            file=sys.stderr,
        )
    for name, r in results.items():
        for st, v in r.get("stages", {}).items():
            print(
                f"  {name} [{st}] facts={v['facts']} strict P={v['strict']['precision']} "
                f"Rf={v['strict']['recall_full']} | all P={v['all']['precision']} "
                f"Rf={v['all']['recall_full']}",
                file=sys.stderr,
            )
    doc = {"gold_items": len(gold), "gold_strict": strict, "scores": results}
    if a.json:
        a.json.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(doc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
