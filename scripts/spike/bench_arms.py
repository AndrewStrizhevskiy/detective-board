#!/usr/bin/env python3
"""Chunk-level comparison of retrieval arms through the real retrieval module (src/detective_board).

Builds a temporary SQLite Store (data/cache/arms-<pid>.db, git-ignored, deleted at exit) from
data/chunks.jsonl and the cached bge-m3 document vectors (bench_retrieval.cache_path; no prefixes,
nothing is re-embedded). Only the questions are embedded through OllamaEmbedder (bge-m3).
Arms: BM25 (OR/AND, +/- stop words), vector, hybrid RRF (k x weights; BM25 on full or stop-stripped
query). Metrics as in bench_retrieval (hit@1/5/10, MRR, recall@10) on the chunk gold.
Run with the project venv: .venv/bin/python scripts/spike/bench_arms.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import sqlite_vec  # noqa: E402
from _common import CHUNKS, ROOT, load_jsonl, write_results  # noqa: E402
from bench_retrieval import cache_path, load_cache, text_hash  # noqa: E402
from chunk_gold import build_gold, load_questions  # noqa: E402

from detective_board.retrieval import (  # noqa: E402
    EmbeddingConfig,
    OllamaEmbedder,
    Store,
    bm25_search,
    hybrid_search,
    load_chunks,
    rrf_fuse,
    vector_search,
)

MODEL, DIM, DEPTH = "bge-m3", 1024, 100
KS = (1, 5, 10)
STOP = set(
    """a an the and or but if of to in on at by for with from as into onto upon about over under
    is are was were be been being am do does did done have has had having will would shall should
    can could may might must not no nor so than too very just also only this that these those there
    here it its he she they them his her their him we you your i me my our us who whom whose which
    what when where why how any some all each every more most other such own same then once out up
    down off again further both few while during before after between through against until
    s t don didn doesn isn wasn""".split()
)
_TOK = re.compile(r"\w+", re.UNICODE)
_POSS = re.compile(r"['’]s\b")


def strip_stop(q: str) -> str:
    toks = _TOK.findall(_POSS.sub("", q))
    kept = [t for t in toks if t.lower() not in STOP]
    return " ".join(kept) or q


class MemoEmbedder:
    """Wrap OllamaEmbedder: each query is sent to Ollama once."""

    def __init__(self, inner):
        self.inner, self.cfg, self.memo = inner, inner.cfg, {}

    def embed_query(self, text):
        if text not in self.memo:
            self.memo[text] = self.inner.embed_query(text)
        return self.memo[text]

    def embed_documents(self, texts):  # never used: corpus vectors come from the cache
        raise RuntimeError("corpus must not be re-embedded")


def build_store(path: Path, chunks, cfg):
    store = Store(path, cfg)
    load_chunks(store, CHUNKS)
    cache = load_cache(cache_path(MODEL, "", 2048, True))
    rid = {r["chunk_id"]: r["rowid_int"] for r in store.db.execute("SELECT chunk_id, rowid_int FROM chunks")}
    rows = []
    for c in chunks:
        e = cache.get(c["chunk_id"])
        if e is None or e["h"] != text_hash(c["text"]):
            raise RuntimeError(f"cached vector missing/stale for {c['chunk_id']}")
        v = e["v"]
        n = sum(x * x for x in v) ** 0.5
        rows.append((rid[c["chunk_id"]], sqlite_vec.serialize_float32([x / n for x in v])))
    with store.db:
        store.db.executemany("INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)", rows)
    return store


def score(q, gold_ids, ids):
    gold = set(gold_ids)
    rank = next((r for r, cid in enumerate(ids, 1) if cid in gold), None)
    row = {
        "id": q["id"],
        "group": q["group"],
        "lang": q["lang"],
        "rank": rank,
        "rr": 1.0 / rank if rank else 0.0,
        "recall@10": len(gold & set(ids[:10])) / len(gold),
        "n_ret": len(ids),
    }
    for k in KS:
        row[f"hit@{k}"] = rank is not None and rank <= k
    return row


GROUPS = {
    "old-en": lambda r: r["group"] == "old-en",
    "old-ru": lambda r: r["group"] == "old-ru",
    "hard": lambda r: r["group"] == "hard",
    "cross": lambda r: r["group"] == "cross",
    "all": lambda r: True,
    "ru": lambda r: r["lang"] == "ru",
    "en": lambda r: r["lang"] == "en",
}


def summarize(rows):
    out = {}
    for g, f in GROUPS.items():
        sel = [r for r in rows if f(r)]
        n = len(sel)
        if not n:
            continue
        d = {"n": n, "mrr": sum(r["rr"] for r in sel) / n, "recall@10": sum(r["recall@10"] for r in sel) / n}
        for k in KS:
            d[f"hit@{k}"] = sum(r[f"hit@{k}"] for r in sel) / n
        out[g] = d
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--keep-db", action="store_true")
    a = ap.parse_args(argv)

    chunks = load_jsonl(CHUNKS)
    questions = load_questions()
    gold, missing = build_gold(questions, chunks)
    if missing:
        print(f"unmapped quotes: {missing}", file=sys.stderr)
        return 2
    cfg = EmbeddingConfig(model=MODEL, dim=DIM)
    db_path = ROOT / "data" / "cache" / f"arms-{os.getpid()}.db"
    store = build_store(db_path, chunks, cfg)
    emb = MemoEmbedder(OllamaEmbedder(cfg, base_url=a.host))
    try:
        # per-question arm outputs, computed once
        arm_out: dict[str, dict[str, list]] = {}
        for q in questions:
            text = q["question"]
            stop = strip_stop(text)
            arm_out[q["id"]] = {
                "bm25-or": bm25_search(store, text, DEPTH, "or"),
                "bm25-and": bm25_search(store, text, DEPTH, "and"),
                "bm25-or-stop": bm25_search(store, stop, DEPTH, "or"),
                "bm25-and-stop": bm25_search(store, stop, DEPTH, "and"),
                "vec": vector_search(store, emb, text, DEPTH),
            }
        # sanity: the module's own hybrid_search == our rrf_fuse over the same arms
        q0 = next(q for q in questions if q["lang"] == "en")
        ref = hybrid_search(store, emb, q0["question"], limit=DEPTH, k=60, candidates=DEPTH)
        mine = rrf_fuse(
            {"bm25": arm_out[q0["id"]]["bm25-or"], "vec": arm_out[q0["id"]]["vec"]}, k=60, limit=DEPTH
        )
        assert [h.chunk_id for h in ref] == [h.chunk_id for h in mine], "hybrid_search != rrf_fuse"

        configs: dict[str, dict] = {}

        def add(name, fn, desc):
            rows = []
            for q in questions:
                ids = [h.chunk_id for h in fn(q)]
                rows.append(score(q, gold[q["id"]]["chunks"], ids) | {"top10": ids[:10]})
            configs[name] = {"desc": desc, "summary": summarize(rows), "rows": rows}

        for name in ("bm25-or", "bm25-and", "bm25-or-stop", "bm25-and-stop", "vec"):
            add(name, lambda q, n=name: arm_out[q["id"]][n], name)
        WS = {"1:1": (1.0, 1.0), "0.5:1": (0.5, 1.0), "1:2": (1.0, 2.0)}
        for bm in ("bm25-or", "bm25-or-stop"):
            for k in (10, 30, 60):
                for wn, (wb, wv) in WS.items():
                    def fn(q, bm=bm, k=k, wb=wb, wv=wv):
                        arms = {"bm25": arm_out[q["id"]][bm], "vec": arm_out[q["id"]]["vec"]}
                        return rrf_fuse(arms, k=k, weights={"bm25": wb, "vec": wv}, limit=DEPTH)

                    add(f"hyb[{bm[5:]}] k={k} w={wn}", fn, f"RRF k={k} bm25:vec={wn}, bm25 arm = {bm}")

        # Russian: BM25 arm on Russian text vs English corpus
        ru_ids = [q["id"] for q in questions if q["lang"] == "ru"]
        ru_bm25_empty = sum(1 for i in ru_ids if not arm_out[i]["bm25-or"])
        ru_bm25_hits = {
            i: len(arm_out[i]["bm25-or"]) for i in ru_ids
        }  # non-empty only if latin tokens/names in the question

        # best config by all hit@5, then MRR (hybrids and vec only)
        cand = [n for n in configs if n == "vec" or n.startswith("hyb")]
        best = max(cand, key=lambda n: (configs[n]["summary"]["all"]["hit@5"], configs[n]["summary"]["all"]["mrr"]))
        best_en = max(
            cand, key=lambda n: (configs[n]["summary"]["en"]["hit@5"], configs[n]["summary"]["en"]["mrr"])
        )

        # rank bucket analysis of misses
        def buckets(name, k):
            rows = configs[name]["rows"]
            miss = [r for r in rows if not r[f"hit@{k}"]]
            b = {"n_miss": len(miss), "rank_k+1..10": 0, "rank_11..50": 0, "rank_51..100": 0, "not_retrieved": 0}
            for r in miss:
                x = r["rank"]
                if x is None:
                    b["not_retrieved"] += 1
                elif x <= 10:
                    b["rank_k+1..10"] += 1
                elif x <= 50:
                    b["rank_11..50"] += 1
                else:
                    b["rank_51..100"] += 1
            return b

        bucket = {n: {f"k={k}": buckets(n, k) for k in (1, 5)} for n in ("vec", best)}

        # query tricks: stop-stripped BM25 inside the best hybrid parameters, EN only
        trick = {}
        m = re.match(r"hyb\[(.*?)\] k=(\d+) w=(\S+)", best)
        bk, bw = m.group(2), m.group(3)
        for bm in ("or", "or-stop"):
            nm = f"hyb[{bm}] k={bk} w={bw}"
            trick[nm] = {g: configs[nm]["summary"][g] for g in ("en", "ru", "all")}

        # failures of the best config at k=5
        qmap = {q["id"]: q for q in questions}
        by_id = {c["chunk_id"]: c for c in chunks}
        fails = []
        for r in configs[best]["rows"]:
            if r["hit@5"]:
                continue
            q = qmap[r["id"]]
            g = gold[q["id"]]["chunks"]
            ao = arm_out[q["id"]]
            rk = lambda lst: {h.chunk_id: i for i, h in enumerate(lst, 1)}  # noqa: E731
            bm_r, v_r = rk(ao["bm25-or"]), rk(ao["vec"])
            top1 = by_id[r["top10"][0]]
            fails.append(
                {
                    "id": q["id"],
                    "group": q["group"],
                    "lang": q["lang"],
                    "question": q["question"],
                    "gold_chunks": g,
                    "n_gold": len(g),
                    "quotes": [e["quote"][:160] for e in gold[q["id"]]["quotes"]],
                    "rank_best": r["rank"],
                    "gold_ranks_bm25": {c: bm_r.get(c) for c in g},
                    "gold_ranks_vec": {c: v_r.get(c) for c in g},
                    "top1": top1["chunk_id"],
                    "top1_snippet": top1["text"][:200].replace("\n", " "),
                    "gold_snippet": by_id[g[0]]["text"][:200].replace("\n", " "),
                    "top1_same_story": top1["story"] in q["expected_stories"],
                }
            )

        data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": MODEL,
            "corpus_chunks": len(chunks),
            "n_questions": len(questions),
            "depth": DEPTH,
            "best": best,
            "best_en": best_en,
            "ru_bm25": {"n_ru": len(ru_ids), "empty_result": ru_bm25_empty, "result_counts": ru_bm25_hits},
            "buckets": bucket,
            "tricks": trick,
            "failures_best_k5": fails,
            "configs": configs,
        }
        j, md = write_results("arms", data, to_markdown(data))
        print(f"best={best}\nwrote {j}\nwrote {md}")
    finally:
        store.close()
        if not a.keep_db:
            db_path.unlink(missing_ok=True)
    return 0


def to_markdown(d):
    p = lambda x: f"{x:.2f}"  # noqa: E731
    cfgs = d["configs"]
    L = [f"# Retrieval arms comparison ({d['timestamp']})", ""]
    L += [
        f"Model {d['model']} (no prefixes), {d['corpus_chunks']} chunks, {d['n_questions']} questions, "
        f"chunk gold (any chunk touching an evidence quote). Ranking depth {d['depth']} per arm; "
        "MRR is over that depth (rank beyond it counts 0). Real `retrieval` module: Store, bm25_search, "
        "vector_search, rrf_fuse (== hybrid_search, asserted).",
        "",
        "Groups: old-en, old-ru, hard, cross, all; plus `ru` (all Russian questions) and `en`.",
        "",
    ]
    for g in ("all", "en", "ru", "old-en", "old-ru", "hard", "cross"):
        n = cfgs["vec"]["summary"][g]["n"]
        L += [
            f"## Group `{g}` (n={n})",
            "",
            "| config | hit@1 | hit@5 | hit@10 | MRR | recall@10 |",
            "|---|---|---|---|---|---|",
        ]
        for name, c in cfgs.items():
            s = c["summary"][g]
            mark = " **(best)**" if name == d["best"] else ""
            L.append(
                f"| {name}{mark} | {p(s['hit@1'])} | {p(s['hit@5'])} | {p(s['hit@10'])} | {p(s['mrr'])} | {p(s['recall@10'])} |"
            )
        L.append("")
    r = d["ru_bm25"]
    L += [
        "## Russian vs BM25",
        "",
        f"{r['n_ru']} Russian questions; BM25 (OR) returned an empty list for {r['empty_result']} of them. "
        f"Result counts for the rest: { {k: v for k, v in r['result_counts'].items() if v} }.",
        "",
        "## Miss buckets (rank of first gold chunk among misses)",
        "",
        "| config | k | misses | rank k+1..10 | 11..50 | 51..100 | not in top 100 |",
        "|---|---|---|---|---|---|---|",
    ]
    for n, bb in d["buckets"].items():
        for k, b in bb.items():
            L.append(
                f"| {n} | {k} | {b['n_miss']} | {b['rank_k+1..10']} | {b['rank_11..50']} | {b['rank_51..100']} | {b['not_retrieved']} |"
            )
    L += ["", "## Query trick: BM25 arm on stop-word-stripped query (best hybrid parameters)", "", "| config | group | hit@1 | hit@5 | hit@10 | MRR |", "|---|---|---|---|---|---|"]
    for n, gs in d["tricks"].items():
        for g, s in gs.items():
            L.append(f"| {n} | {g} | {p(s['hit@1'])} | {p(s['hit@5'])} | {p(s['hit@10'])} | {p(s['mrr'])} |")
    L += ["", f"## Failures of best config `{d['best']}` at k=5 ({len(d['failures_best_k5'])})", ""]
    for f in d["failures_best_k5"]:
        L += [
            f"### {f['id']} [{f['group']}/{f['lang']}] rank={f['rank_best']} n_gold={f['n_gold']}",
            f"- Q: {f['question']}",
            f"- gold chunks: {', '.join(f['gold_chunks'])}",
            f"- gold ranks bm25: {f['gold_ranks_bm25']}; vec: {f['gold_ranks_vec']}",
            f"- top1 {f['top1']} (expected story: {f['top1_same_story']}): {f['top1_snippet']}",
            f"- gold[0]: {f['gold_snippet']}",
            f"- evidence: {f['quotes']}",
            "",
        ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
