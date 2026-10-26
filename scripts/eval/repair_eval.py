#!/usr/bin/env python3
"""Before/after of the extraction repair step (extract/repair.py) on cached model output.

No LLM call: raw outputs are read from copies of extract-cache SQLite files (qwen3:4b,
extract-2.1 by default, the cache key of the pipeline), parsed and grounded with and without
`repair`, ingested into a temp graph per variant, normalised, and scanned with
`find_contradictions` through `InProcessRulesClient` (assume_day None and 1).
Part (b) compares repaired events with the gold events of eval/extraction_gold/ for the gold
chunks that are in the caches.

Usage: repair_eval.py CACHE.sqlite [CACHE2.sqlite ...] [--model qwen3:4b] [--json]
"""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from detective_board.agent.rules_client import InProcessRulesClient  # noqa: E402
from detective_board.extract import normalise  # noqa: E402
from detective_board.extract.cache import ExtractCache  # noqa: E402
from detective_board.extract.ingest import ingest_results  # noqa: E402
from detective_board.extract.llm import FakeClient  # noqa: E402
from detective_board.extract.pipeline import ChunkResult, ExtractConfig, Extractor  # noqa: E402
from detective_board.graph import GraphStore  # noqa: E402
from detective_board.graph.normalize import fold_text, normalize_name  # noqa: E402


def run_variant(
    caches: list[ExtractCache], chunks: dict[str, dict], model: str, repair: bool
) -> list[ChunkResult]:
    out: dict[str, ChunkResult] = {}
    for c in caches:
        ex = Extractor(FakeClient([]), ExtractConfig(model, repair=repair), c)
        for cid, rec in chunks.items():
            if cid not in out and c.get(ex.key(rec["text"])) is not None:
                out[cid] = ex.extract_chunk(cid, rec["story"], rec["text"])
    return [out[k] for k in sorted(out)]


def field_stats(results: list[ChunkResult]) -> dict[str, float]:
    ev = [e for r in results for e in r.extraction.get("events", [])]
    cl = [c for r in results for c in r.extraction.get("claims", [])]
    n, m = len(ev), len(cl)
    return {
        "events": n,
        "ev_with_participants": sum(bool(e["participants"]) for e in ev),
        "ev_time_text": sum(bool(e.get("time_text")) for e in ev),
        "ev_place": sum(bool(e.get("place")) for e in ev),
        "ev_in_speech": sum(bool(e.get("in_speech")) for e in ev),
        "claims": m,
        "cl_deny": sum(c.get("polarity") == "deny" for c in cl),
        "cl_about_person": sum(bool(c.get("about_person")) for c in cl),
        "cl_about_place": sum(bool(c.get("about_place")) for c in cl),
        "cl_about_time": sum(bool(c.get("about_time_text")) for c in cl),
    }


def graph_stats(
    results: list[ChunkResult], chunks: dict[str, dict], repair: bool, tmp: Path
) -> dict[str, dict]:
    db = tmp / f"graph-{'after' if repair else 'before'}.sqlite"
    store = GraphStore(str(db))
    ingest_results(store, results, chunks, repair=False)  # variant already repaired (or not)
    out: dict[str, dict] = {}
    for story in sorted({r.story for r in results}):
        rep = normalise.apply(store, story)
        row = {
            "events_timed": rep.events_timed,
            "events_dated": rep.events_dated,
            "claims_structured": rep.claims_structured,
            "claim_reasons": rep.claim_reasons,
        }
        for label, day in (("none", None), ("day1", 1)):
            cl = InProcessRulesClient(store, assume_day=day)
            res = cl.call("find_contradictions", {"story": story}, timeout=30)
            fs = res.get("findings", [])
            row[f"findings_assume_{label}"] = len(fs)
            row[f"findings_{label}_by_rule"] = dict(Counter(f["rule"] for f in fs))
        out[story] = row
    store.close()
    return out


# --- (b) gold comparison


def _toks(s: str) -> set[str]:
    return set(fold_text(s).split())


def _match_events(pred: list[dict], gold: list[dict]) -> list[tuple[dict, dict]]:
    pairs, used = [], set()
    for g in gold:
        gt = _toks(g["quote"])
        best, bi = 0.0, -1
        for i, p in enumerate(pred):
            if i in used:
                continue
            pt = _toks(p["quote"])
            j = len(gt & pt) / max(1, len(gt | pt))
            if j > best:
                best, bi = j, i
        if bi >= 0 and best >= 0.5:
            used.add(bi)
            pairs.append((pred[bi], g))
    return pairs


def _name_keys(name: str, ents: list[dict]) -> set[str]:
    """Keys naming the same person: the name, its entity's aliases, and the surname."""
    k = normalize_name(name)
    keys = {k}
    for e in ents:
        if e["type"] != "person":
            continue
        names = {normalize_name(x) for x in [e["name"], *e.get("aliases", [])]}
        if k in names:
            keys |= names
    keys |= {x.split()[-1] for x in keys if x and len(x.split()) > 1}
    return {x for x in keys if x}


def _same_person(a: str, ents_a: list[dict], b: str, ents_b: list[dict]) -> bool:
    return bool(_name_keys(a, ents_a) & _name_keys(b, ents_b))


def gold_compare(results: list[ChunkResult], gold_dir: Path) -> dict:
    gold_by = {}
    for f in sorted(glob.glob(str(gold_dir / "*.json"))):
        g = json.load(open(f, encoding="utf-8"))
        gold_by[g["chunk_id"]] = g
    tp = fp = fn = 0
    t_agree = t_gold_has = t_both = t_fill_when_none = n_gold_none = 0
    p_agree = p_gold_has = p_both = p_fill_when_none = n_gp_none = 0
    speech = Counter()
    matched = n_gold_ev = 0
    chunks = []
    for r in results:
        g = gold_by.get(r.chunk_id)
        if g is None or not r.extraction:
            continue
        chunks.append(r.chunk_id)
        pe, ge = r.extraction.get("events", []), g["gold"]["events"]
        pairs = _match_events(pe, ge)
        matched += len(pairs)
        n_gold_ev += len(ge)
        for p, gd in pairs:
            gp = gd.get("participants", [])
            pp = p.get("participants", [])
            hit_g = set()
            for x in pp:
                m = [
                    i
                    for i, y in enumerate(gp)
                    if _same_person(x, r.extraction["entities"], y, g["gold"]["entities"])
                ]
                if m:
                    tp += 1
                    hit_g.add(m[0])
                else:
                    fp += 1
            fn += len(gp) - len(hit_g)
            speech[bool(p.get("in_speech"))] += 1
            gt_, pt_ = gd.get("time_text"), p.get("time_text")
            if gt_:
                t_gold_has += 1
                if pt_:
                    t_both += 1
                    t_agree += bool(_toks(gt_) & _toks(pt_))
            else:
                n_gold_none += 1
                t_fill_when_none += bool(pt_)
            gpl, ppl = gd.get("place"), p.get("place")
            if gpl:
                p_gold_has += 1
                if ppl:
                    p_both += 1
                    p_agree += bool(_toks(gpl) & _toks(ppl))
            else:
                n_gp_none += 1
                p_fill_when_none += bool(ppl)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return {
        "gold_chunks_in_cache": chunks,
        "gold_events": n_gold_ev,
        "matched_events": matched,
        "participants_tp_fp_fn": [tp, fp, fn],
        "participants_precision": round(prec, 3),
        "participants_recall": round(rec, 3),
        "pred_in_speech_true_false": [speech[True], speech[False]],
        "time": {
            "gold_has": t_gold_has,
            "pred_has_of_gold_has": t_both,
            "agree_of_both": t_agree,
            "gold_none": n_gold_none,
            "pred_filled_when_gold_none": t_fill_when_none,
        },
        "place": {
            "gold_has": p_gold_has,
            "pred_has_of_gold_has": p_both,
            "agree_of_both": p_agree,
            "gold_none": n_gp_none,
            "pred_filled_when_gold_none": p_fill_when_none,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("caches", nargs="+", type=Path)
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--chunks", type=Path, default=ROOT / "data" / "chunks.jsonl")
    ap.add_argument("--gold", type=Path, default=ROOT / "eval" / "extraction_gold")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    chunks = {}
    for line in a.chunks.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            chunks[rec["chunk_id"]] = rec
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        caches = []
        for i, p in enumerate(a.caches):  # copies: SQLite would write -wal/-shm next to the file
            dst = tmp / f"cache{i}.sqlite"
            shutil.copy(p, dst)
            caches.append(ExtractCache(dst))
        report: dict = {}
        for name, repair in (("before", False), ("after", True)):
            res = run_variant(caches, chunks, a.model, repair)
            report[name] = {
                "chunks": len(res),
                "fields": field_stats(res),
                "graph": graph_stats(res, chunks, repair, tmp),
                "gold": gold_compare(res, a.gold),
            }
            if repair:
                tot: dict[str, int] = Counter()
                for r in res:
                    for k, v in r.repair.get("reasons", {}).items():
                        tot[k] += v
                report[name]["repair_reasons"] = dict(sorted(tot.items()))
    print(json.dumps(report, indent=1, ensure_ascii=False) if a.json else _table(report))


def _table(rep: dict) -> str:
    b, a = rep["before"], rep["after"]
    rows = [f"chunks: {b['chunks']}", f"{'metric':34}{'before':>10}{'after':>10}"]
    for k, v in b["fields"].items():
        rows.append(f"{k:34}{v:>10}{a['fields'][k]:>10}")
    for story in b["graph"]:
        for k in b["graph"][story]:
            bv, av = b["graph"][story][k], a["graph"][story][k]
            rows.append(f"{story[:12] + '.' + k:34}{json.dumps(bv):>10}{json.dumps(av):>10}")
    rows.append("gold " + json.dumps(b["gold"]["gold_chunks_in_cache"]))
    for k in b["gold"]:
        if k != "gold_chunks_in_cache":
            rows.append(f"gold.{k:29}{json.dumps(b['gold'][k]):>10}{json.dumps(a['gold'][k]):>10}")
    rows.append("repair reasons: " + json.dumps(a.get("repair_reasons")))
    return "\n".join(rows)


if __name__ == "__main__":
    main()
