#!/usr/bin/env python3
"""Extractive-mode candidate recall: share of answerable questions with a gold sentence on offer.

    uv run python eval/extractive_recall.py [--stamp S]

Same questions, retrieval (real hybrid_search, cached query vectors; no Ollama) and gold mapping as
eval/evidence_in_prompt.py. For each variant the candidate list of the extractive prompt is built
with the real `extractive.candidates_for` / `_render`: retrieved chunks k, sentences per chunk
(IDF scorer over the WHOLE chunk text), a global cap, and what the cap drops (retrieval rank order
vs score). The baseline is the current default: k=4, rank_full windows (top-1 whole, 60-word
windows), 6 per chunk, cap 24, score order. A question is covered when one candidate sentence
contains, or overlaps >= 50% with (the part of the quote inside that chunk), a gold quote.
Prompt tokens = chars/4 of the real prompt (system prompt included). Questions with no cached
query vector are skipped and counted. Output: docs/spike/results/extractive-recall-<stamp>.{json,md}.
All numbers are measured on the questions the pipeline was tuned on: optimistic.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
sys.path.insert(0, str(ROOT / "eval"))

from chunk_gold import find_spans  # noqa: E402
from evidence_in_prompt import (  # noqa: E402
    CHUNKS,
    CLEAN,
    QEMB,
    QEMB_SEED,
    RESULTS,
    RRF,
    CachedEmbedder,
    load_all,
    wilson,
)

from detective_board.agent import extractive as ex  # noqa: E402
from detective_board.agent.context import sources_from_hits  # noqa: E402
from detective_board.agent.window import idf_from_jsonl  # noqa: E402
from detective_board.index.build import CONFIG, DB  # noqa: E402
from detective_board.retrieval import Store  # noqa: E402
from detective_board.retrieval.search import hybrid_search  # noqa: E402

KS = [4, 6, 8, 10]
PER = [4, 6, 8]
CAPS = [24, 32, 40]
ORDERS = ["rank", "score"]
BUDGET = 700
BASE = {
    "name": "current",
    "k": 4,
    "per": 6,
    "cap": 24,
    "order": "score",
    "windows": True,
    "max_tokens": 1200,
}


def overlap_ok(gold: list[tuple[int, int]], cs: int, ce: int, a: int, b: int) -> bool:
    for s, e in gold:
        lo, hi = max(s, cs), min(e, ce)
        if hi > lo and min(hi, b) - max(lo, a) >= 0.5 * (hi - lo):
            return True
    return False


def evaluate(v: dict, qs: list[dict], idf) -> dict:
    cov, toks, gold_frac = [], [], []
    for q in qs:
        hits = q["hits"][: v["k"]]
        if v.get("windows"):
            srcs = sources_from_hits(
                [q["hit_objs"][c["chunk_id"]] for c in hits],
                q["question"],
                60,
                idf=idf,
                full_top1=True,
            )
        else:
            srcs = sources_from_hits([q["hit_objs"][c["chunk_id"]] for c in hits])
        p = ex.build_prompt(
            q["question"], srcs, idf, per_source=v["per"], total=v["cap"],
            max_tokens=v.get("max_tokens", BUDGET), order=v["order"],
        )  # fmt: skip
        toks.append(p.tokens)
        by_n = {i + 1: c for i, c in enumerate(hits)}
        hit_flags = []
        for c in p.candidates:
            ch = by_n[c.n]
            base = ch["char_start"]
            hit_flags.append(
                any(
                    ch["story"] == story
                    and overlap_ok(
                        gs, ch["char_start"], ch["char_end"], base + c.start, base + c.end
                    )
                    for story, gs in q["gold_spans"]
                )
            )
        cov.append(any(hit_flags))
        gold_frac.append((sum(hit_flags), len(hit_flags)))
    ru = [i for i, q in enumerate(qs) if q["lang"] == "ru"]
    n = len(qs)
    k = sum(cov)
    return {
        **v,
        "n": n,
        "covered": k,
        "ci": [round(x, 3) for x in wilson(k, n)],
        "ru_n": len(ru),
        "ru_covered": sum(cov[i] for i in ru),
        "gold_sentence_share": round(sum(g for g, _ in gold_frac) / max(1, sum(t for _, t in gold_frac)), 4),
        "tok_mean": round(statistics.mean(toks), 1),
        "tok_p95": sorted(toks)[int(0.95 * (len(toks) - 1))],
        "tok_max": max(toks),
        "sentences_mean": round(statistics.mean(t for _, t in gold_frac), 1),
        "uncovered": [q["id"] for q, c in zip(qs, cov, strict=True) if not c],
    }  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    a = ap.parse_args()

    chunks = [json.loads(x) for x in CHUNKS.read_text().splitlines() if x.strip()]
    by_id = {c["chunk_id"]: c for c in chunks}
    idf = idf_from_jsonl(str(CHUNKS))
    cache: dict[str, list[float]] = {}
    for p in (QEMB_SEED, QEMB):
        if p.exists():
            cache |= json.loads(p.read_text())
    all_qs = load_all()
    qs = [q for q in all_qs if q["question"] in cache]
    skipped = [q["id"] for q in all_qs if q["question"] not in cache]
    clean: dict[str, str] = {}
    for q in qs:
        q["gold_spans"] = []
        for story, quote in q["quotes"]:
            if story not in clean:
                clean[story] = (CLEAN / f"{story}.txt").read_text(encoding="utf-8")
            q["gold_spans"].append((story, find_spans(clean[story], quote)))
    emb = CachedEmbedder(cache)
    with Store(DB, CONFIG) as store:
        for q in qs:
            hs = hybrid_search(store, emb, q["question"], limit=max(KS), **RRF)
            q["hits"] = [by_id[h.chunk_id] for h in hs]
            q["hit_objs"] = {h.chunk_id: h for h in hs}

    rows = [evaluate(BASE, qs, idf)]
    for k, per, cap, order in product(KS, PER, CAPS, ORDERS):
        rows.append(
            evaluate({"name": f"k{k}/p{per}/c{cap}/{order}", "k": k, "per": per, "cap": cap, "order": order}, qs, idf)
        )  # fmt: skip
    for k, mt in product(KS, [850, 1000, 1200]):
        v = {
            "name": f"k{k}/p8/c40/score/max{mt}",
            "k": k,
            "per": 8,
            "cap": 40,
            "order": "score",
            "max_tokens": mt,
        }
        rows.append(evaluate(v, qs, idf))  # fmt: skip
    ok = [r for r in rows[1:] if r["tok_p95"] <= BUDGET and "max" not in r["name"]]
    ok.sort(key=lambda r: (-r["covered"], r["tok_mean"]))
    out = {
        "stamp": a.stamp,
        "n": len(qs),
        "skipped_no_vector": skipped,
        "n_ru": sum(q["lang"] == "ru" for q in qs),
        "budget_p95": BUDGET,
        "best_under_budget": [r["name"] for r in ok[:8]],
        "rows": rows,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"extractive-recall-{a.stamp}.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False)
    )
    (RESULTS / f"extractive-recall-{a.stamp}.md").write_text(render(out))
    print(f"n={len(qs)} skipped={len(skipped)}")
    for r in [rows[0], *ok[:8]]:
        print(
            f"{r['name']:<22} cov {r['covered']}/{r['n']} ci {r['ci']} ru {r['ru_covered']}/{r['ru_n']} "
            f"gold-share {r['gold_sentence_share']:.3f} tok {r['tok_mean']}/{r['tok_p95']} sents {r['sentences_mean']}"
        )  # fmt: skip
    return 0


def render(o: dict) -> str:
    L = [
        f"# Extractive candidate recall ({o['stamp']})",
        "",
        f"No LLM. n = {o['n']} answerable questions (Russian: {o['n_ru']}); skipped, no cached query vector: "
        f"{len(o['skipped_no_vector'])} {o['skipped_no_vector']}.",
        "",
        "Covered = a candidate sentence contains / overlaps >= 50% with a gold quote (the part inside its chunk). "
        "Tokens = chars/4 of the real selection prompt (system prompt included) after the guard that drops the lowest-scoring sentences while over 700 tokens (current default: 1200). "
        "`order`: what the global cap drops (rank = the worst-ranked chunks' sentences, score = the lowest-scoring). "
        "`current` = k=4, top-1 whole chunk + 60-word windows, 6 per chunk, cap 24.",
        "",
        "Caveat: tuned and measured on the same questions (the pipeline was developed on them; ~100 variants were "
        "compared): optimistic. One question = about 1 point; differences of 1-3 questions are noise.",
        "",
        "| variant | covered | 95% CI | RU | gold share of sentences | sentences | tok mean | tok p95 | tok max |",
        "|---|--:|---|--:|--:|--:|--:|--:|--:|",
    ]
    for r in o["rows"]:
        L.append(
            f"| {r['name']} | {r['covered']}/{r['n']} = {r['covered'] / r['n']:.0%} | "
            f"{r['ci'][0]:.0%}-{r['ci'][1]:.0%} | {r['ru_covered']}/{r['ru_n']} | "
            f"{r['gold_sentence_share']:.1%} | {r['sentences_mean']} | {r['tok_mean']:.0f} | {r['tok_p95']} | {r['tok_max']} |"
        )
    L += ["", f"Best with p95 <= {o['budget_p95']} tokens: {o['best_under_budget']}", ""]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
