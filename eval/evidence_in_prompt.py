#!/usr/bin/env python3
"""Evidence-in-prompt: share of answerable questions whose gold quote reaches the prompt (no LLM).

    uv run python eval/evidence_in_prompt.py [--stamp S]

Questions: answerable ones of eval/golden/questions.jsonl (gold_quotes) plus eval/spike_questions.jsonl
and eval/spike_questions_hard.jsonl (evidence). Retrieval: the real hybrid_search over
data/index/db.sqlite (RRF k=30, weights bm25:vec 0.5:1; query vectors cached in
data/cache/evidence_qemb.json, bge-m3 via Ollama only for missing ones). Windows: agent.window.best_window
with IDF from data/chunks.jsonl. Prompt tokens: the real context.build_messages over the windows, chars/4.
A question is covered when a gold quote (matched in data/clean with whitespace/quote normalisation) lies
inside, or overlaps >= 50% (its part inside that chunk) with, the shown window(s) of one of the top_k chunks.
Strategies: base (one best_window), multi (up to 2 non-adjacent windows of ~W/2 words each),
rank (top-1 chunk gets a larger window, the rest W). Output: docs/spike/results/evidence-<stamp>.{json,md}.
The agent's relevance gate and graph/tool sources are NOT modelled.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))

from chunk_gold import find_spans, load_questions  # noqa: E402

from detective_board.agent.context import Source, build_messages, estimate_tokens  # noqa: E402
from detective_board.agent.window import (  # noqa: E402
    best_window,
    content_words,
    idf_from_jsonl,
    name_words,
    sentence_spans,
)
from detective_board.index.build import CONFIG, DB  # noqa: E402
from detective_board.retrieval import OllamaEmbedder, Store  # noqa: E402
from detective_board.retrieval.search import hybrid_search  # noqa: E402

OLLAMA = "http://localhost:11434"
CHUNKS = ROOT / "data" / "chunks.jsonl"
CLEAN = ROOT / "data" / "clean"
RESULTS = ROOT / "docs" / "spike" / "results"
QEMB = ROOT / "data" / "cache" / "evidence_qemb.json"
QEMB_SEED = ROOT / "data" / "cache" / "answer_check_qemb.json"
RRF = {"k": 30, "weights": {"bm25": 0.5, "vec": 1.0}}
TOP_KS = [3, 4, 5, 6, 8]
WINDOWS = [60, 80, 110, 150, 0]  # 0 = full chunk
RANK_TOP1 = {"2x": 2.0, "full": 0.0}  # top-1 window = 2*W words, or the full chunk
BUDGETS = [1000, 1200, 1500]
NONE = None


# ----------------------------------------------------------------------------- questions
def load_all() -> list[dict]:
    qs = load_questions(
        ROOT / "eval/spike_questions.jsonl", ROOT / "eval/spike_questions_hard.jsonl"
    )
    for line in (ROOT / "eval/golden/questions.jsonl").read_text().splitlines():
        r = json.loads(line) if line.strip() else None
        if r and r["answerable"] and r["gold_quotes"]:
            qs.append(
                {
                    "id": r["id"],
                    "lang": r["lang"],
                    "group": "golden",
                    "question": r["question"],
                    "quotes": [(g["story"], g["quote"]) for g in r["gold_quotes"]],
                }
            )
    return qs


def query_vectors(questions: list[str]) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    for p in (QEMB_SEED, QEMB):
        if p.exists():
            cache |= json.loads(p.read_text())
    todo = [q for q in questions if q not in cache]
    if todo:
        emb = OllamaEmbedder(CONFIG, base_url=OLLAMA)
        for t in todo:
            cache[t] = emb.embed_query(t)
        QEMB.parent.mkdir(parents=True, exist_ok=True)
        QEMB.write_text(json.dumps(cache))
    return cache


class CachedEmbedder:
    def __init__(self, vectors: dict[str, list[float]]):
        self.cfg, self.vectors = CONFIG, vectors

    def embed_query(self, text: str) -> list[float]:
        return self.vectors[text]

    def embed_documents(self, texts):  # pragma: no cover
        raise RuntimeError("documents are never embedded here")


# ----------------------------------------------------------------------------- windows
def _weights(question: str, idf) -> dict[str, float]:
    q = content_words(question)
    if idf:
        top = max(idf.values())
        w = {x: idf.get(x, top) for x in q}
        for x in name_words(question) & w.keys():
            w[x] *= 0.6
        return w
    return dict.fromkeys(q, 1.0)


def _score(text: str, a: int, b: int, weight: dict[str, float]) -> float:
    return sum(weight[w] for w in content_words(text[a:b]) & weight.keys())


def windows_for(text: str, question: str, words: int, idf, n: int = 1, ratio: float = 1.0):
    """List of (start, end) offsets. words<=0 -> full chunk. n=2: first best window of
    `words` words, then the best window of `words*ratio` words that is not adjacent to it."""
    if words <= 0:
        return [(0, len(text))]
    w1 = best_window(text, question, words, idf)
    out = [(w1.start, w1.end)]
    if n < 2 or (w1.start == 0 and w1.end == len(text)):
        return out
    spans = sentence_spans(text)
    weight = _weights(question, idf)
    best = None
    # candidate zones: strictly before / after the first window, one sentence gap apart
    left = [s for s in spans if s[1] <= w1.start]
    right = [s for s in spans if s[0] >= w1.end]
    for zone in (left[:-1], right[1:]):
        if not zone:
            continue
        a, b = zone[0][0], zone[-1][1]
        sub = text[a:b]
        ww = best_window(sub, question, max(1, int(words * ratio)), idf)
        s0, e0 = a + ww.start, a + ww.end
        sc = _score(text, s0, e0, weight)
        if sc > 0 and (best is None or sc > best[0]):
            best = (sc, s0, e0)
    if best:
        out.append((best[1], best[2]))
    return sorted(out)


def shown(text: str, spans: list[tuple[int, int]]) -> str:
    return " […] ".join(text[a:b] for a, b in spans)


# ----------------------------------------------------------------------------- coverage
def covered(gold: list[tuple[int, int]], chunk: dict, spans: list[tuple[int, int]]) -> bool:
    """Is any gold quote span (absolute offsets, same story) kept by the windows of this chunk?"""
    cs = chunk["char_start"]
    for s, e in gold:
        lo, hi = max(s, cs), min(e, chunk["char_end"])
        if hi <= lo:
            continue
        got = sum(max(0, min(hi, cs + b) - max(lo, cs + a)) for a, b in spans)
        if got >= 0.5 * (hi - lo):
            return True
    return False


def prompt_tokens(question: str, chunks: list[dict], spans: list[list[tuple[int, int]]]) -> int:
    srcs = [
        Source(
            i + 1, c["chunk_id"], c["story"], c["char_start"], c["char_end"],
            shown(c["text"], sp), "vector", "source_text", summary="retrieved chunk (rrf 0.0333)",
        )
        for i, (c, sp) in enumerate(zip(chunks, spans, strict=True))
    ]  # fmt: skip
    _, chars = build_messages(question, srcs, [], "")
    return estimate_tokens(chars)


# ----------------------------------------------------------------------------- run
def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def configs() -> list[dict]:
    out = []
    for k in TOP_KS:
        for w in WINDOWS:
            out.append({"strategy": "base", "top_k": k, "w": w, "top1": None})
            if w:
                out.append({"strategy": "multi", "top_k": k, "w": w, "top1": None})
                for name in RANK_TOP1:
                    out.append({"strategy": f"rank-{name}", "top_k": k, "w": w, "top1": name})
    return out


def spans_for(cfg: dict, rank: int, chunk: dict, question: str, idf) -> list[tuple[int, int]]:
    t = chunk["text"]
    if cfg["strategy"] == "multi":
        return windows_for(t, question, cfg["w"] // 2, idf, n=2, ratio=1.0)
    if cfg["strategy"].startswith("rank") and rank == 0:
        mult = RANK_TOP1[cfg["top1"]]
        words = 0 if mult == 0 else int(cfg["w"] * mult)
        return windows_for(t, question, words, idf)
    return windows_for(t, question, cfg["w"], idf)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    a = ap.parse_args()

    chunks = [json.loads(x) for x in CHUNKS.read_text().splitlines() if x.strip()]
    by_id = {c["chunk_id"]: c for c in chunks}
    idf = idf_from_jsonl(str(CHUNKS))
    qs = load_all()
    clean: dict[str, str] = {}
    for q in qs:
        gold_spans, gold_chunks = [], set()  # per quote: (story, spans)
        for story, quote in q["quotes"]:
            if story not in clean:
                clean[story] = (CLEAN / f"{story}.txt").read_text(encoding="utf-8")
            sp = find_spans(clean[story], quote)
            gold_spans.append((story, sp))
            for c in chunks:
                if c["story"] == story and any(
                    c["char_start"] < e and s < c["char_end"] for s, e in sp
                ):
                    gold_chunks.add(c["chunk_id"])
        q["gold_spans"], q["gold_chunks"] = gold_spans, gold_chunks
    vectors = query_vectors([q["question"] for q in qs])
    emb = CachedEmbedder(vectors)
    with Store(DB, CONFIG) as store:
        for q in qs:
            hits = hybrid_search(store, emb, q["question"], limit=max(TOP_KS), **RRF)
            q["hits"] = [by_id[h.chunk_id] for h in hits]

    def q_covered(q: dict, chs: list[dict], sps: list[list[tuple[int, int]]], mode: str) -> bool:
        res = []
        for story, gs in q["gold_spans"]:
            res.append(
                any(
                    c["story"] == story and covered(gs, c, sp)
                    for c, sp in zip(chs, sps, strict=True)
                )
            )
        return any(res) if mode == "any" else all(res)

    rows = []
    per_q: dict[str, dict[str, bool]] = {}
    for cfg in configs():
        key = f"{cfg['strategy']}|k{cfg['top_k']}|w{cfg['w']}"
        cov_any, cov_all, chunk_hit, miss, toks = [], [], [], [], []
        for q in qs:
            chs = q["hits"][: cfg["top_k"]]
            sps = [spans_for(cfg, i, c, q["question"], idf) for i, c in enumerate(chs)]
            ca = q_covered(q, chs, sps, "any")
            ch = any(c["chunk_id"] in q["gold_chunks"] for c in chs)
            cov_any.append(ca)
            cov_all.append(q_covered(q, chs, sps, "all"))
            chunk_hit.append(ch)
            miss.append(ch and not ca)
            toks.append(prompt_tokens(q["question"], chs, sps))
            per_q.setdefault(key, {})[q["id"]] = ca
        langs = {"ru": [i for i, q in enumerate(qs) if q["lang"] == "ru"]}
        langs["en"] = [i for i, q in enumerate(qs) if q["lang"] != "ru"]
        rows.append(
            {
                **cfg,
                "key": key,
                "n": len(qs),
                "covered": sum(cov_any),
                "covered_all_quotes": sum(cov_all),
                "chunk_hit": sum(chunk_hit),
                "window_miss": sum(miss),
                "ci": [round(x, 3) for x in wilson(sum(cov_any), len(qs))],
                "ru_n": len(langs["ru"]),
                "ru_covered": sum(cov_any[i] for i in langs["ru"]),
                "en_n": len(langs["en"]),
                "en_covered": sum(cov_any[i] for i in langs["en"]),
                "tok_mean": round(statistics.mean(toks), 1),
                "tok_p95": sorted(toks)[int(0.95 * (len(toks) - 1))],
                "tok_max": max(toks),
            }
        )

    # Pareto per budget: feasible = p95 tokens <= budget; best coverage, ties -> fewer mean tokens
    pareto = {}
    for b in BUDGETS:
        ok = [r for r in rows if r["tok_p95"] <= b]
        ok.sort(key=lambda r: (-r["covered"], r["tok_mean"]))
        best_by_strategy = {}
        for r in ok:
            best_by_strategy.setdefault(r["strategy"], r["key"])
        pareto[b] = {"top": [r["key"] for r in ok[:8]], "best_by_strategy": best_by_strategy}
    # upper bound: chunk-level coverage by top_k
    ub = {
        k: sum(any(c["chunk_id"] in q["gold_chunks"] for c in q["hits"][:k]) for q in qs)
        for k in TOP_KS
    }
    focus = {k: {i: v for i, v in d.items() if i in ("g007", "g028")} for k, d in per_q.items()}
    out = {
        "stamp": a.stamp,
        "n_questions": len(qs),
        "n_ru": sum(q["lang"] == "ru" for q in qs),
        "groups": {g: sum(q["group"] == g for q in qs) for g in sorted({q["group"] for q in qs})},
        "chunk_level_by_top_k": ub,
        "rows": rows,
        "pareto": pareto,
        "g007_g028": focus,
        "uncovered_at_max": [q["id"] for q in qs if not per_q["base|k8|w0"][q["id"]]],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"evidence-{a.stamp}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    (RESULTS / f"evidence-{a.stamp}.md").write_text(render(out))
    print(f"wrote {RESULTS}/evidence-{a.stamp}.{{json,md}}")
    return 0


# ----------------------------------------------------------------------------- report
def pc(k: int, n: int) -> str:
    return f"{k}/{n} = {k / n:.0%}" if n else "-"


def table(rows: list[dict]) -> list[str]:
    out = [
        "| strategy | top_k | W | covered | 95% CI | all-quotes | chunk hit | chunk hit, window miss | RU | tok mean | tok p95 |",
        "|---|--:|--:|--:|---|--:|--:|--:|--:|--:|--:|",
    ]
    for r in rows:
        w = "full" if r["w"] == 0 else r["w"]
        out.append(
            f"| {r['strategy']} | {r['top_k']} | {w} | {pc(r['covered'], r['n'])} | "
            f"{r['ci'][0]:.0%}-{r['ci'][1]:.0%} | {r['covered_all_quotes']} | {r['chunk_hit']} | "
            f"{r['window_miss']} | {r['ru_covered']}/{r['ru_n']} | {r['tok_mean']:.0f} | {r['tok_p95']} |"
        )
    return out


def render(o: dict) -> str:
    rows = {r["key"]: r for r in o["rows"]}
    L = [
        f"# Evidence in prompt ({o['stamp']})",
        "",
        f"No LLM. n = {o['n_questions']} answerable questions ({o['groups']}; Russian: {o['n_ru']}). "
        "Hybrid RRF k=30, bm25:vec 0.5:1, real `hybrid_search`; `best_window` with IDF from chunks.jsonl; "
        "tokens = chars/4 of the real `build_messages` prompt (system prompt + source headers + question).",
        "",
        "## Caveats",
        "- All numbers are on the questions the pipeline was tuned on (window scoring, RRF weights, chunking); "
        "treat them as optimistic. n is small: one question = ~1.2 points; see the Wilson CIs (about +-9 points).",
        "- 'Covered' = a gold quote is inside or >= 50% overlapped by a shown window of a retrieved chunk; "
        "this is necessary, not sufficient, for a correct answer. Question covered when ANY gold quote is kept "
        "(`all-quotes` column = every quote).",
        "- Not modelled: the agent's relevance gate, graph/tool sources, retry with more chunks, history.",
        "- Picking the best of ~150 configs on the same questions inflates the winner; differences of 1-3 questions are noise.",
        "- multi = 2 windows of ~W/2 words (same total W, joined with ` [...] `); rank-* = top-1 chunk gets 2*W words "
        "(`rank-2x`) or the full chunk (`rank-full`), others W.",
        "",
        "## Chunk-level ceiling (gold chunk within top_k, window-independent)",
        "",
        "| top_k | " + " | ".join(str(k) for k in o["chunk_level_by_top_k"]) + " |",
        "|---|" + "--:|" * len(o["chunk_level_by_top_k"]),
        "| gold chunk retrieved | "
        + " | ".join(pc(v, o["n_questions"]) for v in o["chunk_level_by_top_k"].values())
        + " |",
        "",
        "## Pareto per token budget (feasible = p95 prompt tokens <= budget)",
    ]
    for b, p in o["pareto"].items():
        L += ["", f"### <= {b} tokens", "", "Best per strategy:", ""]
        L += table([rows[k] for k in p["best_by_strategy"].values()])
        L += ["", "Top 8 overall:", ""] + table([rows[k] for k in p["top"]])
    L += ["", "## g007 / g028 (covered?)", ""]
    for k, d in o["g007_g028"].items():
        if k.startswith("base|k3|") or k.startswith("base|k5|w110") or k.startswith("base|k8|w0"):
            L.append(f"- `{k}`: {d}")
    L += ["", f"Not covered even at top_k=8 + full chunks: {o['uncovered_at_max']}", ""]
    L += ["## All configurations", ""] + table(o["rows"])
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
