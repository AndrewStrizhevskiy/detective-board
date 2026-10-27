#!/usr/bin/env python3
"""Sentence-index candidate recall (no LLM): current candidate builder vs 'sentence-hybrid'.

    uv run python eval/sentence_recall.py [--stamp S] [--index data/index/sentences.sqlite]

Same 86 answerable questions, chunk retrieval (real hybrid_search, RRF k=30, 0.5:1) and gold mapping
as eval/extractive_recall.py. Query vectors come from data/cache/evidence_qemb.json and
answer_check_qemb.json; a missing one is embedded with bge-m3 (Ollama) and cached. Variants:

  current          the shipped candidate builder: top-6 chunks, whole text, 8 per chunk, cap 40,
                   850 tokens (extractive.build_prompt)
  sentence-hybrid  the shipped sentence-index builder (extractive.build_hybrid_prompt): top 12
                   sentences of the sentence index over the whole corpus + best 2 sentences of
                   each of the top 2 chunk hits, cap 40, 850 tokens
  ablations        fewer / more index sentences, no safety net, sentence index only

Covered = a candidate sentence contains or overlaps >= 50% (the part inside its chunk) with a gold
quote. Prompt tokens = chars/4 of the real selection prompt. 'sentence-hybrid' parameters are the
ones fixed in the task (12 / 2 / 2), not searched, but the questions are the ones the pipeline was
developed on: optimistic. Output: docs/spike/results/sentence-recall-<stamp>.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
sys.path.insert(0, str(ROOT / "eval"))

from chunk_gold import find_spans  # noqa: E402
from evidence_in_prompt import (  # noqa: E402
    CHUNKS,
    CLEAN,
    RESULTS,
    RRF,
    CachedEmbedder,
    load_all,
    query_vectors,
    wilson,
)
from extractive_recall import overlap_ok  # noqa: E402

from detective_board.agent import extractive as ex  # noqa: E402
from detective_board.agent.backends import SentenceResult  # noqa: E402
from detective_board.agent.context import sources_from_hits  # noqa: E402
from detective_board.agent.window import idf_from_jsonl  # noqa: E402
from detective_board.index.build import CONFIG, DB  # noqa: E402
from detective_board.retrieval import Hit, Store  # noqa: E402
from detective_board.retrieval.search import hybrid_search  # noqa: E402
from detective_board.retrieval.sentences import SentenceStore, sentence_search  # noqa: E402

K_CHUNKS = 6
MAX_TOKENS = 850
VARIANTS = [
    {"name": "current", "kind": "chunk"},
    {"name": "sentence-hybrid", "kind": "hybrid", "sent": 12, "safe": 2, "per": 2},
    {"name": "sentence-hybrid, no safety net", "kind": "hybrid", "sent": 12, "safe": 0, "per": 2},
    {"name": "sentence-hybrid, top 8", "kind": "hybrid", "sent": 8, "safe": 2, "per": 2},
    {"name": "sentence-hybrid, top 20", "kind": "hybrid", "sent": 20, "safe": 2, "per": 2},
    {"name": "sentence index only, top 12 (no token guard)", "kind": "raw", "sent": 12},
]


def chunk_hit(by_id: dict, cid: str) -> Hit:
    c = by_id[cid]
    return Hit(cid, c["story"], c["char_start"], c["char_end"], 0.0, text=c["text"])


def evaluate(v: dict, qs: list[dict], idf) -> dict:
    cov, toks, nsent = [], [], []
    for q in qs:
        srcs = sources_from_hits([q["hit_objs"][c["chunk_id"]] for c in q["hits"][:K_CHUNKS]])
        flags: list[bool] = []
        if v["kind"] == "raw":
            cands = [(h.chunk_id, h.start, h.end) for h in q["sent_hits"][: v["sent"]]]
            toks.append(0)
            by_cid = {c["chunk_id"]: c for c in q["chunk_rows"].values()}
            for cid, a, b in cands:
                ch = by_cid[cid]
                flags.append(
                    any(
                        ch["story"] == st
                        and overlap_ok(gs, ch["char_start"], ch["char_end"], ch["char_start"] + a, ch["char_start"] + b)
                        for st, gs in q["gold_spans"]
                    )
                )  # fmt: skip
        else:
            if v["kind"] == "chunk":
                p = ex.build_prompt(q["question"], srcs, idf, per_source=8, total=40, max_tokens=MAX_TOKENS, order="score")  # fmt: skip
                used = srcs
            else:
                found = SentenceResult(
                    q["sent_hits"][: v["sent"]],
                    {h.chunk_id: chunk_hit(q["chunk_rows"], h.chunk_id) for h in q["sent_hits"][: v["sent"]]},
                )  # fmt: skip
                p, used = ex.build_hybrid_prompt(
                    q["question"], srcs, found, idf, top_sentences=v["sent"],
                    safety_chunks=v["safe"], safety_per_chunk=v["per"], total=40, max_tokens=MAX_TOKENS,
                )  # fmt: skip
            toks.append(p.tokens)
            by_n = {s.n: s for s in used}
            for c in p.candidates:
                s = by_n[c.n]
                flags.append(
                    any(
                        s.story == st and overlap_ok(gs, s.char_start, s.char_end, s.char_start + c.start, s.char_start + c.end)
                        for st, gs in q["gold_spans"]
                    )
                )  # fmt: skip
        cov.append(any(flags))
        nsent.append(len(flags))
    ru = [i for i, q in enumerate(qs) if q["lang"] == "ru"]
    k, n = sum(cov), len(qs)
    kr = sum(cov[i] for i in ru)
    return {
        "name": v["name"],
        "n": n,
        "covered": k,
        "ci": [round(x, 3) for x in wilson(k, n)],
        "ru_n": len(ru),
        "ru_covered": kr,
        "ru_ci": [round(x, 3) for x in wilson(kr, len(ru))],
        "en_covered": k - kr,
        "en_n": n - len(ru),
        "tok_mean": round(statistics.mean(toks), 1),
        "tok_p95": sorted(toks)[int(0.95 * (len(toks) - 1))],
        "tok_max": max(toks),
        "sentences_mean": round(statistics.mean(nsent), 1),
        "uncovered": [q["id"] for q, c in zip(qs, cov, strict=True) if not c],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--index", type=Path, default=ROOT / "data" / "index" / "sentences.sqlite")
    a = ap.parse_args()

    chunks = [json.loads(x) for x in CHUNKS.read_text().splitlines() if x.strip()]
    by_id = {c["chunk_id"]: c for c in chunks}
    idf = idf_from_jsonl(str(CHUNKS))
    qs = load_all()
    cache = query_vectors([q["question"] for q in qs])  # embeds (bge-m3) only the missing ones
    emb = CachedEmbedder(cache)
    clean: dict[str, str] = {}
    for q in qs:
        q["gold_spans"] = []
        for story, quote in q["quotes"]:
            if story not in clean:
                clean[story] = (CLEAN / f"{story}.txt").read_text(encoding="utf-8")
            q["gold_spans"].append((story, find_spans(clean[story], quote)))
    with Store(DB, CONFIG) as store, SentenceStore(a.index, CONFIG) as sst:
        n_sent = sst.count()
        for q in qs:
            hs = hybrid_search(store, emb, q["question"], limit=K_CHUNKS, **RRF)
            q["hits"] = [by_id[h.chunk_id] for h in hs]
            q["hit_objs"] = {h.chunk_id: h for h in hs}
            q["sent_hits"] = sentence_search(sst, q["question"], cache[q["question"]], 50, 50, 20)
            q["chunk_rows"] = by_id
    rows = [evaluate(v, qs, idf) for v in VARIANTS]
    out = {
        "stamp": a.stamp,
        "n": len(qs),
        "n_ru": sum(q["lang"] == "ru" for q in qs),
        "sentences_indexed": n_sent,
        "max_tokens": MAX_TOKENS,
        "rows": rows,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"sentence-recall-{a.stamp}.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False)
    )
    (RESULTS / f"sentence-recall-{a.stamp}.md").write_text(render(out))
    for r in rows:
        print(
            f"{r['name']:<46} cov {r['covered']}/{r['n']} ci {r['ci']} ru {r['ru_covered']}/{r['ru_n']} "
            f"tok {r['tok_mean']}/{r['tok_p95']}/{r['tok_max']} sents {r['sentences_mean']}"
        )  # fmt: skip
    return 0


def render(o: dict) -> str:
    L = [
        f"# Sentence-index candidate recall ({o['stamp']})",
        "",
        f"No LLM. n = {o['n']} answerable questions (Russian: {o['n_ru']}); sentence index: {o['sentences_indexed']} sentences. "
        "Covered = a candidate sentence contains / overlaps >= 50% with a gold quote (the part inside its chunk). "
        f"Tokens = chars/4 of the real selection prompt, token guard {o['max_tokens']}. "
        "`current` = the candidate builder that ships without the sentence index (top-6 chunks, whole text, 8 per chunk, cap 40). "
        "`sentence-hybrid` = top 12 sentences of the index over the whole corpus + best 2 lexical sentences of each of the top 2 chunks.",
        "",
        "Caveat: measured on the questions the pipeline was developed on (the scorer, RRF constants and chunking were tuned on them); "
        "the sentence-hybrid parameters (12 / 2 / 2) were fixed up front, the ablation rows are for context, not selection. "
        "One question is about 1.2 points; Wilson intervals are shown. Necessary, not sufficient, for a correct answer: the model still has to pick the sentence.",
        "",
        "| variant | covered | 95% CI | RU | EN | sentences | tok mean | tok p95 | tok max |",
        "|---|--:|---|--:|--:|--:|--:|--:|--:|",
    ]
    for r in o["rows"]:
        L.append(
            f"| {r['name']} | {r['covered']}/{r['n']} = {r['covered'] / r['n']:.0%} | {r['ci'][0]:.0%}-{r['ci'][1]:.0%} | "
            f"{r['ru_covered']}/{r['ru_n']} | {r['en_covered']}/{r['en_n']} | {r['sentences_mean']} | {r['tok_mean']:.0f} | {r['tok_p95']} | {r['tok_max']} |"
        )
    L += ["", "Not covered, per variant:", ""]
    L += [f"- {r['name']}: {', '.join(r['uncovered']) or '-'}" for r in o["rows"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
