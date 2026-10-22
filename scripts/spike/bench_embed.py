#!/usr/bin/env python3
"""Phase 0 spike: embedding model throughput, dimension, RSS and a retrieval sanity check.

Stdlib only. Ollama API fields (verified in docs/api.md): POST /api/embed with
  model, input (string | list of strings), truncate (default true), options, keep_alive;
  response: embeddings, total_duration, load_duration, prompt_eval_count (ns durations).
Throughput: embed N chunks (default 50, evenly spaced across data/chunks.jsonl) in batches,
  1 warmup pass + --runs measured passes, mean ± stdev of chunks/s.
Retrieval: embed ALL chunks (or --retrieval-chunks N evenly spaced), embed the questions from
  eval/spike_questions.jsonl, cosine top-5, hit@5 / hit@1 at story level (hit = any of the top-k
  chunks belongs to expected_story). Reported separately for en (15), ru (5) and the 5 en originals
  of the ru questions (paired comparison).
Some models need query/document prefixes (see their model cards); none are applied unless given via
  --query-prefix MODEL=TEXT / --doc-prefix MODEL=TEXT.
Note: with truncate=true over-long inputs are silently cut to the model context; check model cards.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import (  # noqa: E402
    CHUNKS,
    ROOT,
    Http,
    RssSampler,
    fmt,
    load_jsonl,
    mem_available_mib,
    stats,
    write_results,
)

QUESTIONS = ROOT / "eval" / "spike_questions.jsonl"
CLEAN = ROOT / "data" / "clean"


def norm(t: str) -> str:
    return re.sub(
        r"\s+", " ", t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    )


def validate_questions(qs: list[dict], chunks: list[dict]) -> list[str]:
    """Check expected_story exists and the evidence quote is literally in data/clean/<story>.txt."""
    errs = []
    stories = {c["story"] for c in chunks}
    ids = set()
    for q in qs:
        if q["id"] in ids:
            errs.append(f"duplicate id {q['id']}")
        ids.add(q["id"])
        if q["expected_story"] not in stories:
            errs.append(f"{q['id']}: unknown story {q['expected_story']}")
            continue
        text = norm((CLEAN / f"{q['expected_story']}.txt").read_text(encoding="utf-8"))
        if norm(q["evidence"]) not in text:
            errs.append(f"{q['id']}: evidence not found in {q['expected_story']}")
    en = [q for q in qs if q["lang"] == "en"]
    ru = [q for q in qs if q["lang"] == "ru"]
    if len(en) != 15 or len(ru) != 5:
        errs.append(f"expected 15 en + 5 ru questions, got {len(en)} + {len(ru)}")
    for q in ru:
        o = next((x for x in en if x["id"] == q.get("translation_of")), None)
        if not o or o["expected_story"] != q["expected_story"]:
            errs.append(f"{q['id']}: bad translation_of")
    return errs


def evenly(xs: list, n: int) -> list:
    if n >= len(xs):
        return list(xs)
    return [xs[int(i * len(xs) / n)] for i in range(n)]


def embed(http, model, texts, a, options):
    r = http.post(
        "/api/embed",
        {
            "model": model,
            "input": texts,
            "truncate": a.truncate,
            "keep_alive": a.keep_alive,
            "options": options,
        },
    )
    return r["embeddings"], r


def embed_all(http, model, texts, a, options):
    out, load, ptoks = [], 0.0, 0
    for i in range(0, len(texts), a.batch):
        e, r = embed(http, model, texts[i : i + a.batch], a, options)
        out += e
        load += (r.get("load_duration") or 0) / 1e9
        ptoks += r.get("prompt_eval_count") or 0
    return out, load, ptoks


def unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def retrieval(http, model, chunks, qs, a, options, qp, dp):
    sub = evenly(chunks, a.retrieval_chunks) if a.retrieval_chunks else chunks
    # always include chunks of expected stories only if full corpus; with a subset the result is labelled
    t0 = time.perf_counter()
    docs, _, _ = embed_all(http, model, [dp + c["text"] for c in sub], a, options)
    docs = [unit(d) for d in docs]
    t_docs = time.perf_counter() - t0
    qv, _, _ = embed_all(http, model, [qp + q["question"] for q in qs], a, options)
    qv = [unit(v) for v in qv]
    rows = []
    for q, v in zip(qs, qv):
        sc = sorted(
            ((sum(x * y for x, y in zip(v, d)), i) for i, d in enumerate(docs)), reverse=True
        )[:5]
        top = [sub[i]["story"] for _, i in sc]
        rows.append(
            {
                "id": q["id"],
                "lang": q["lang"],
                "expected": q["expected_story"],
                "top5_stories": top,
                "top5_chunks": [sub[i]["chunk_id"] for _, i in sc],
                "hit1": top[0] == q["expected_story"],
                "hit5": q["expected_story"] in top,
            }
        )
    ru_orig = {q["translation_of"] for q in qs if q["lang"] == "ru"}

    def hr(sel, k):
        sel = list(sel)
        return {
            "n": len(sel),
            f"hit@{k}": (sum(r[f"hit{k}"] for r in sel) / len(sel)) if sel else None,
        }

    summ = {}
    for name, f in (
        ("en_all", lambda r: r["lang"] == "en"),
        ("ru", lambda r: r["lang"] == "ru"),
        ("en_paired_with_ru", lambda r: r["id"] in ru_orig),
    ):
        sel = [r for r in rows if f(r)]
        summ[name] = {"n": len(sel), "hit@5": hr(sel, 5)["hit@5"], "hit@1": hr(sel, 1)["hit@1"]}
    return {
        "corpus_chunks": len(sub),
        "embed_corpus_s": t_docs,
        "summary": summ,
        "per_question": rows,
    }


def unload_all(http):
    """No other model may stay resident, otherwise RSS of the previous model is added to this one."""
    for loaded in http.get("/api/ps").get("models", []):
        http.post(
            "/api/generate",
            {"model": loaded["name"], "prompt": "", "keep_alive": 0, "stream": False},
        )
    time.sleep(3.0)


def bench_model(http, model, chunks, qs, a):
    res = {"model": model}
    if not http.available(model):
        res["error"] = "model not installed (not in /api/tags)"
        return res
    unload_all(http)
    opts = {"num_ctx": a.num_ctx}
    qp, dp = a.query_prefix.get(model, ""), a.doc_prefix.get(model, "")
    texts = [dp + c["text"] for c in evenly(chunks, a.n_chunks)]
    res["mem_available_before_mib"] = round(mem_available_mib(), 1)
    with RssSampler(a.sample_interval) as rss:
        runs = []
        for i in range(a.warmup + a.runs):
            t0 = time.perf_counter()
            emb, load, ptoks = embed_all(http, model, texts, a, opts)
            dt_s = time.perf_counter() - t0
            runs.append(
                {
                    "warmup": i < a.warmup,
                    "seconds": dt_s,
                    "chunks_per_s": len(texts) / dt_s,
                    "load_s": load,
                    "prompt_tokens": ptoks,
                }
            )
            print(
                f"  {model} {'warmup' if i < a.warmup else 'run'} {i}: {len(texts) / dt_s:.2f} chunks/s",
                file=sys.stderr,
            )
        res["dim"] = len(emb[0])
        res["n_embedded"] = len(emb)
        meas = [r for r in runs if not r["warmup"]]
        res["runs"] = runs
        res["chunks_per_s"] = stats([r["chunks_per_s"] for r in meas])
        res["prompt_tokens_per_pass"] = stats([r["prompt_tokens"] for r in meas])
        res["first_pass_load_s"] = runs[0]["load_s"]
        if not a.skip_retrieval:
            res["retrieval"] = retrieval(http, model, chunks, qs, a, opts, qp, dp)
    res["rss"] = rss.result()
    res["mem_available_after_mib"] = round(mem_available_mib(), 1)
    res["prefixes"] = {"query": qp, "doc": dp}
    unload_all(http)
    return res


def to_markdown(d: dict) -> str:
    a = d["args"]
    L = [
        f"# Embedding benchmark ({d['timestamp']})",
        "",
        f"Ollama {d['ollama_version']}; {a['n_chunks']} chunks/pass, batch {a['batch']}, num_ctx {a['num_ctx']}, "
        f"truncate={a['truncate']}; {a['warmup']} warmup + {a['runs']} measured passes (mean ± stdev). "
        f"RSS sampled every {a['sample_interval']}s over all `ollama` processes (covers throughput + retrieval embedding).",
        "",
        "| model | dim | chunks/s | prompt toks/pass | first-pass load s | peak RSS MiB (total / anon) | MemAvail before→after MiB |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in d["models"]:
        if "error" in m:
            L.append(f"| {m['model']} | {m['error']} |" + " |" * 5)
            continue
        L.append(
            f"| {m['model']} | {m['dim']} | {fmt(m['chunks_per_s'])} | {fmt(m['prompt_tokens_per_pass'], 0)} | "
            f"{m['first_pass_load_s']:.2f} | {m['rss']['peak_rss_total_mib']} / {m['rss']['peak_rss_anon_mib']} | "
            f"{m['mem_available_before_mib']}→{m['mem_available_after_mib']} |"
        )
    if not a["skip_retrieval"]:
        L += [
            "",
            "## Retrieval sanity (story-level hit rate over chunks)",
            "",
            "| model | corpus chunks | en hit@5 (n=15) | en hit@1 | ru hit@5 (n=5) | ru hit@1 | en hit@5 on the same 5 | prefixes q / doc |",
            "|---|---|---|---|---|---|---|---|",
        ]
        p = lambda x: "n/a" if x is None else f"{x:.2f}"  # noqa: E731
        for m in d["models"]:
            if "retrieval" not in m:
                continue
            s = m["retrieval"]["summary"]
            L.append(
                f"| {m['model']} | {m['retrieval']['corpus_chunks']} | {p(s['en_all']['hit@5'])} | {p(s['en_all']['hit@1'])} | "
                f"{p(s['ru']['hit@5'])} | {p(s['ru']['hit@1'])} | {p(s['en_paired_with_ru']['hit@5'])} | "
                f"`{m['prefixes']['query']}` / `{m['prefixes']['doc']}` |"
            )
        L += [
            "",
            "Small n (15 / 5): differences of one question are noise; treat as a smoke test, not a ranking.",
        ]
    return "\n".join(L) + "\n"


def kv(items, flag, ap):
    out = {}
    for s in items or []:
        if "=" not in s:
            ap.error(f"{flag} expects MODEL=TEXT, got {s!r}")
        k, v = s.split("=", 1)
        out[k] = v
    return out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "models", nargs="+", help="e.g. bge-m3 nomic-embed-text all-minilm snowflake-arctic-embed"
    )
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--n-chunks", type=int, default=50)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--num-ctx", type=int, default=2048)
    ap.add_argument(
        "--truncate", type=lambda s: s.lower() != "false", default=True, help="true|false"
    )
    ap.add_argument("--keep-alive", default="10m")
    ap.add_argument("--sample-interval", type=float, default=0.5)
    ap.add_argument(
        "--retrieval-chunks",
        type=int,
        default=0,
        help="0 = whole corpus; N = N evenly spaced chunks",
    )
    ap.add_argument("--skip-retrieval", action="store_true")
    ap.add_argument("--query-prefix", action="append", metavar="MODEL=TEXT")
    ap.add_argument("--doc-prefix", action="append", metavar="MODEL=TEXT")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="validate args/questions/chunks; no Ollama calls, no files",
    )
    a = ap.parse_args(argv)
    if min(a.n_chunks, a.batch, a.runs) < 1 or a.warmup < 0 or a.sample_interval <= 0:
        ap.error("need n-chunks,batch,runs>=1, warmup>=0, sample-interval>0")
    a.query_prefix = kv(a.query_prefix, "--query-prefix", ap)
    a.doc_prefix = kv(a.doc_prefix, "--doc-prefix", ap)
    for k in list(a.query_prefix) + list(a.doc_prefix):
        if k not in a.models:
            ap.error(f"prefix given for model not in list: {k}")
    return a


def main(argv=None):
    a = parse_args(argv)
    chunks = load_jsonl(CHUNKS)
    qs = load_jsonl(QUESTIONS)
    errs = validate_questions(qs, chunks)
    if errs:
        print("\n".join("question check failed: " + e for e in errs), file=sys.stderr)
        return 2
    if a.dry_run:
        print(
            f"[dry-run] models={a.models} n_chunks={a.n_chunks} batch={a.batch} runs={a.runs}+{a.warmup} num_ctx={a.num_ctx}"
        )
        print(
            f"[dry-run] {len(chunks)} chunks / {len({c['story'] for c in chunks})} stories; "
            f"{sum(q['lang'] == 'en' for q in qs)} en + {sum(q['lang'] == 'ru' for q in qs)} ru questions; all evidence quotes found in data/clean"
        )
        print("[dry-run] no network used. OK")
        return 0
    http = Http(a.host)
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ollama_version": http.get("/api/version")["version"],
        "args": vars(a),
        "models": [],
    }
    for m in a.models:
        print(f"== {m}", file=sys.stderr)
        data["models"].append(bench_model(http, m, chunks, qs, a))
    j, md = write_results("embed", data, to_markdown(data))
    print(f"wrote {j}\nwrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
