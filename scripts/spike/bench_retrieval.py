#!/usr/bin/env python3
"""Chunk-level retrieval benchmark for embedding models (stdlib only).

Per model: embed the whole corpus ONCE (vectors cached on disk, resumable), embed the questions
(eval/spike_questions.jsonl 20 + eval/spike_questions_hard.jsonl), rank all chunks by cosine and
report hit@1/5/10, MRR and recall@10 against the gold chunk sets built by chunk_gold.py
(any chunk touching any evidence quote). Groups: old-en, old-ru, hard, cross (+ all).
Cross-story questions have gold chunks in two stories; hit = any gold chunk, recall = share of all.
Cache: data/cache/emb/<model>-<sha1 of doc prefix/num_ctx/truncate>.jsonl, one line per chunk
  {"id", "h" (sha1 of text), "v"}; appended after every batch, so an interrupted run resumes.
Ollama: POST /api/embed via bench_embed.embed_all. Nothing is called with --dry-run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import CHUNKS, ROOT, Http, load_jsonl, write_results  # noqa: E402
from bench_embed import embed_all, kv, unit  # noqa: E402
from chunk_gold import build_gold, load_questions  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache" / "emb"
GROUPS = ("old-en", "old-ru", "hard", "cross")
KS = (1, 5, 10)


def text_hash(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:12]


def cache_path(model: str, doc_prefix: str, num_ctx: int, truncate: bool, cache_dir=CACHE_DIR) -> Path:
    settings = json.dumps({"doc_prefix": doc_prefix, "num_ctx": num_ctx, "truncate": truncate},
                          sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha1(settings.encode("utf-8")).hexdigest()[:10]
    return Path(cache_dir) / f"{re.sub(r'[^A-Za-z0-9._-]', '_', model)}-{sha}.jsonl"


def load_cache(path: Path) -> dict[str, dict]:
    """id -> {"h", "v"}; a torn last line (interrupted write) is ignored."""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                out[r["id"]] = {"h": r["h"], "v": r["v"]}
            except (json.JSONDecodeError, KeyError):
                continue
    return out


def embed_corpus(chunks, doc_prefix, embed, path: Path, batch=10, log=lambda s: None):
    """Return unit vectors for chunks (same order); embed only what is missing from the cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(path)
    todo = [c for c in chunks if cache.get(c["chunk_id"], {}).get("h") != text_hash(doc_prefix + c["text"])]
    log(f"cache {path.name}: {len(chunks) - len(todo)}/{len(chunks)} present, embedding {len(todo)}")
    if todo:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" if path.stat().st_size and not _ends_nl(path) else "")
            for i in range(0, len(todo), batch):
                part = todo[i:i + batch]
                vecs = embed([doc_prefix + c["text"] for c in part])
                if len(vecs) != len(part):
                    raise RuntimeError(f"embedder returned {len(vecs)} vectors for {len(part)} texts")
                for c, v in zip(part, vecs):
                    r = {"id": c["chunk_id"], "h": text_hash(doc_prefix + c["text"]),
                         "v": [round(x, 6) for x in v]}
                    cache[c["chunk_id"]] = {"h": r["h"], "v": r["v"]}
                    f.write(json.dumps(r) + "\n")
                f.flush()
                log(f"  embedded {min(i + batch, len(todo))}/{len(todo)}")
    return [unit(cache[c["chunk_id"]]["v"]) for c in chunks]


def _ends_nl(path: Path) -> bool:
    with open(path, "rb") as f:
        f.seek(-1, 2)
        return f.read(1) == b"\n"


def rank_chunks(qv, docs):
    """Indices of docs by descending cosine (unit vectors); ties keep corpus order."""
    sc = [sum(x * y for x, y in zip(qv, d)) for d in docs]
    return sorted(range(len(docs)), key=lambda i: (-sc[i], i))


def score_question(q, gold_ids, order, chunks):
    ids = [chunks[i]["chunk_id"] for i in order]
    gold = set(gold_ids)
    rank = next((r for r, cid in enumerate(ids, 1) if cid in gold), None)
    top10 = ids[:10]
    stories = [chunks[i]["story"] for i in order[:5]]
    row = {"id": q["id"], "group": q["group"], "lang": q["lang"], "expected_stories": q["expected_stories"],
           "gold_chunks": sorted(gold), "rank": rank, "rr": (1.0 / rank) if rank else 0.0,
           "recall@10": len(gold & set(top10)) / len(gold) if gold else None,
           "story_hit@5": any(s in q["expected_stories"] for s in stories), "top10": top10}
    for k in KS:
        row[f"hit@{k}"] = rank is not None and rank <= k
    return row


def summarize(rows):
    def agg(sel):
        n = len(sel)
        if not n:
            return {"n": 0}
        d = {"n": n, "mrr": sum(r["rr"] for r in sel) / n,
             "recall@10": sum(r["recall@10"] for r in sel) / n,
             "story_hit@5": sum(r["story_hit@5"] for r in sel) / n}
        for k in KS:
            d[f"hit@{k}"] = sum(r[f"hit@{k}"] for r in sel) / n
        return d
    out = {g: agg([r for r in rows if r["group"] == g]) for g in GROUPS}
    out["all"] = agg(rows)
    return out


def evaluate(model, chunks, questions, gold, embed, doc_prefix="", query_prefix="", path=None,
             batch=10, log=lambda s: None):
    docs = embed_corpus(chunks, doc_prefix, embed, path, batch, log)
    qv = [unit(v) for v in embed([query_prefix + q["question"] for q in questions])]
    rows = [score_question(q, gold[q["id"]]["chunks"], rank_chunks(v, docs), chunks)
            for q, v in zip(questions, qv)]
    return {"model": model, "dim": len(docs[0]), "corpus_chunks": len(chunks),
            "cache": str(path), "prefixes": {"query": query_prefix, "doc": doc_prefix},
            "summary": summarize(rows), "per_question": rows}


def to_markdown(d):
    p = lambda x: "n/a" if x is None else f"{x:.2f}"  # noqa: E731
    L = [f"# Chunk-level retrieval benchmark ({d['timestamp']})", "",
         "Hit = any gold chunk (chunk touching an evidence quote) in top-k; recall@10 = share of gold chunks "
         "in top 10; MRR over the full ranking. `story@5` = old story-level hit@5, for reference.", "",
         "| model | group | n | hit@1 | hit@5 | hit@10 | MRR | recall@10 | story@5 |", "|---|---|---|---|---|---|---|---|---|"]
    for m in d["models"]:
        if "error" in m:
            L.append(f"| {m['model']} | {m['error']} |" + " |" * 7)
            continue
        for g in (*GROUPS, "all"):
            s = m["summary"][g]
            if not s["n"]:
                continue
            L.append(f"| {m['model']} | {g} | {s['n']} | {p(s['hit@1'])} | {p(s['hit@5'])} | {p(s['hit@10'])} | "
                     f"{p(s['mrr'])} | {p(s['recall@10'])} | {p(s['story_hit@5'])} |")
    return "\n".join(L) + "\n"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("models", nargs="+")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--num-ctx", type=int, default=2048)
    ap.add_argument("--truncate", type=lambda s: s.lower() != "false", default=True, help="true|false")
    ap.add_argument("--keep-alive", default="5m")
    ap.add_argument("--cache-dir", default=str(CACHE_DIR))
    ap.add_argument("--query-prefix", action="append", metavar="MODEL=TEXT")
    ap.add_argument("--doc-prefix", action="append", metavar="MODEL=TEXT")
    ap.add_argument("--dry-run", action="store_true", help="validate gold, show cache state; no Ollama, no files")
    a = ap.parse_args(argv)
    if a.batch < 1:
        ap.error("batch must be >= 1")
    a.query_prefix = kv(a.query_prefix, "--query-prefix", ap)
    a.doc_prefix = kv(a.doc_prefix, "--doc-prefix", ap)
    for k in list(a.query_prefix) + list(a.doc_prefix):
        if k not in a.models:
            ap.error(f"prefix given for model not in list: {k}")
    return a


def main(argv=None):
    a = parse_args(argv)
    chunks = load_jsonl(CHUNKS)
    questions = load_questions()
    gold, missing = build_gold(questions, chunks)
    if missing:
        print("\n".join(f"unmapped quote {m['id']}: {m['quote']!r}" for m in missing), file=sys.stderr)
        return 2
    if a.dry_run:
        grp = {g: sum(q["group"] == g for q in questions) for g in GROUPS}
        print(f"[dry-run] {len(chunks)} chunks, {len(questions)} questions {grp}, all quotes mapped")
        for m in a.models:
            dp = a.doc_prefix.get(m, "")
            path = cache_path(m, dp, a.num_ctx, a.truncate, a.cache_dir)
            have = load_cache(path)
            ok = sum(have.get(c["chunk_id"], {}).get("h") == text_hash(dp + c["text"]) for c in chunks)
            print(f"[dry-run] {m}: cache {path} has {ok}/{len(chunks)}; q-prefix={a.query_prefix.get(m, '')!r} "
                  f"d-prefix={dp!r}")
        print("[dry-run] no network used. OK")
        return 0
    http = Http(a.host)
    data = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "args": vars(a), "models": []}
    opts = {"num_ctx": a.num_ctx}
    for m in a.models:
        print(f"== {m}", file=sys.stderr)
        if not http.available(m):
            data["models"].append({"model": m, "error": "model not installed (not in /api/tags)"})
            continue
        dp, qp = a.doc_prefix.get(m, ""), a.query_prefix.get(m, "")
        embed = (lambda texts, m=m: embed_all(http, m, texts, a, opts)[0])
        path = cache_path(m, dp, a.num_ctx, a.truncate, a.cache_dir)
        data["models"].append(evaluate(m, chunks, questions, gold, embed, dp, qp, path, a.batch,
                                       log=lambda s: print(s, file=sys.stderr)))
    j, md = write_results("retrieval", data, to_markdown(data))
    print(f"wrote {j}\nwrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
