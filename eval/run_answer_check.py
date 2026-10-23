#!/usr/bin/env python3
"""Answer-model check: the real Agent (retrieval-only path) per candidate LLM on 12 golden questions.

    uv run python eval/run_answer_check.py                  # full run (hours; use nohup)
    uv run python eval/run_answer_check.py --summary-only --stamp <stamp>

What runs: detective_board.agent.Agent + OllamaLLM-compatible client, HybridRetriever over
data/index/db.sqlite (RRF k=30, weights bm25:vec 0.5:1, OR mode: best config of
docs/spike/results/arms-*.md), NO graph, NO MCP tools. One model process at a time: the 12 query
embeddings are computed first (bge-m3) and cached, bge-m3 is then unloaded; every LLM is unloaded
and followed by a pause before the next one. Results are appended per question to
docs/spike/results/answers-<stamp>-<model>.jsonl (resumable with the same --stamp); the markdown
summary is docs/spike/results/answers-<stamp>.md. A 'bare LLM' baseline (same question, no
retrieval, no system prompt) runs for the best model (composite score, see `composite`).

Crude proxies, all computed mechanically (see the 'caveats' section of the summary): key-fact
coverage = share of content words of expected_answer found in the answer text (citations stripped).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))

from chunk_gold import find_spans, touching_chunks  # noqa: E402

from detective_board.agent import Agent, AgentConfig, HybridRetriever  # noqa: E402
from detective_board.agent.events import (  # noqa: E402
    AnswerToken,
    CitationCheck,
    EnrichedQuery,
    Final,
    RetrievalResults,
    RouteDecided,
)
from detective_board.index.build import CONFIG, DB  # noqa: E402
from detective_board.retrieval import OllamaEmbedder, Store  # noqa: E402

OLLAMA = "http://localhost:11434"
QUESTIONS = ROOT / "eval" / "golden" / "questions.jsonl"
CLEAN = ROOT / "data" / "clean"
CHUNKS = ROOT / "data" / "chunks.jsonl"
RESULTS = ROOT / "docs" / "spike" / "results"
QEMB_CACHE = ROOT / "data" / "cache" / "answer_check_qemb.json"

# (ollama model, think flag)  -- order is the run order
MODELS: list[tuple[str, bool]] = [
    ("qwen3:4b", False),
    ("qwen3:4b-instruct", False),
    ("gemma3:4b", False),
    ("qwen3:8b", False),
    ("qwen2.5:7b", False),
]
NUM_CTX, NUM_CTX_BIG, NUM_PREDICT, TEMPERATURE, SEED = 4096, 8192, 300, 0.0, 42
RRF = {"k": 30, "weights": {"bm25": 0.5, "vec": 1.0}}

# Fixed, deterministic selection: 2 fact, 2 testimony-contradiction, 2 relation, 1 chronology,
# 1 alibi, 2 out-of-corpus, 1 adversarial, 1 Russian. g047/g056 are out-of-corpus on purpose with
# different failure modes (famous canon vs plausible number); g057 is a false-premise question.
SELECTION = [
    "g001", "g007",  # fact
    "g028", "g032",  # testimony-contradiction
    "g016", "g019",  # relation
    "g022",          # chronology
    "g038",          # alibi
    "g047", "g056",  # out-of-corpus
    "g057",          # adversarial (false premise)
    "g062",          # Russian
]  # fmt: skip
# correct_premise needs a marker: the answer must carry the corrected fact, not just any text.
PREMISE_MARKERS = {"g057": ["roylott"]}

# ----------------------------------------------------------------------------- text proxies
_STOP = frozenset(
    "the and for are was were has have had not but with from that this these those its his her "
    "their they them she him you your our out who whom what when where which while into onto "
    "than then there here been being will would could should can may might did does done also "
    "any all one two per via about after before over under upon very more most some such only "
    "because said says say not nor yes how why".split()
)
_WORD = re.compile(r"[^\W_]{3,}")
_CITE = re.compile(r'\[\d+(?:\s*:\s*".+?")?\s*\]', re.S)
_REFUSE_PHRASES = re.compile(
    r"nothing about this|not (mentioned|stated|found|covered|contained|in (the|these))|"
    r"no (mention|record|information|evidence|such)|cannot (answer|find|determine)|can't (answer|find)|"
    r"don'?t (have|know)|do not (have|know)|doesn'?t (appear|exist|mention|contain)|"
    r"does not (appear|exist|mention|contain)|there is no|there'?s no|unable to|"
    r"не (упоминается|говорится|сказано|найден)|нет (информации|упоминан)",
    re.I,
)


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP}


def coverage(expected: str, answer: str) -> float:
    """Share of content words of `expected` found in `answer` (citations stripped)."""
    want = content_words(expected)
    if not want:
        return 0.0
    have = content_words(_CITE.sub(" ", answer))
    return len(want & have) / len(want)


# ----------------------------------------------------------------------------- gold chunks
def gold_for(q: dict, chunks_by_story: dict[str, list[dict]]) -> dict[str, Any]:
    """Gold spans (story, start, end) and the chunks touching them, from the verbatim quotes."""
    spans: list[tuple[str, int, int]] = []
    chunk_ids: list[str] = []
    missing = 0
    for gq in q["gold_quotes"]:
        story = gq["story"]
        text = (CLEAN / f"{story}.txt").read_text(encoding="utf-8")
        found = find_spans(text, gq["quote"])
        if not found:
            missing += 1
        spans += [(story, s, e) for s, e in found]
        for cid in touching_chunks(chunks_by_story.get(story, []), [(s, e) for s, e in found]):
            if cid not in chunk_ids:
                chunk_ids.append(cid)
    return {"spans": spans, "chunks": chunk_ids, "missing_quotes": missing}


# ----------------------------------------------------------------------------- Ollama plumbing
def _post_json(path: str, payload: dict, timeout: float = 600.0) -> dict:
    req = urllib.request.Request(
        OLLAMA + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (local Ollama)
        return json.load(r)


def unload(model: str) -> None:
    """keep_alive=0 evicts the model; /api/embed for embedding models, /api/generate otherwise."""
    try:
        if model.startswith("bge-"):
            _post_json("/api/embed", {"model": model, "input": "x", "keep_alive": 0}, 120)
        else:
            _post_json("/api/generate", {"model": model, "keep_alive": 0}, 120)
    except Exception as e:  # best effort
        print(f"[warn] unload {model}: {e}", flush=True)


def running_models() -> list[str]:
    with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10) as r:  # noqa: S310
        return [m["name"] for m in json.load(r).get("models", [])]


class MeteredLLM:
    """Streaming /api/chat client implementing the agent's LLM protocol, with num_predict and the
    final-chunk counters (prompt_eval_count, eval_count, durations) kept per call."""

    def __init__(self, model: str, think: bool, num_ctx: int = NUM_CTX, timeout: float = 600.0):
        self.model, self.think, self.num_ctx, self.timeout = model, think, num_ctx, timeout
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> Iterator[str]:
        opts: dict[str, Any] = {
            "temperature": temperature,
            "num_ctx": self.num_ctx,
            "num_predict": NUM_PREDICT,
        }
        if seed is not None:
            opts["seed"] = seed
        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": True,
            "think": self.think,
            "options": opts,
        }
        rec: dict[str, Any] = {"num_ctx": self.num_ctx, "first_piece_s": None, "pieces": 0}
        self.calls.append(rec)
        t0 = time.monotonic()
        req = urllib.request.Request(
            OLLAMA + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            resp_cm = urllib.request.urlopen(req, timeout=self.timeout)  # noqa: S310
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:400]}") from e
        with resp_cm as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("error"):
                    raise RuntimeError(f"ollama error: {obj['error']}")
                piece = obj.get("message", {}).get("content", "")
                if piece:
                    if rec["first_piece_s"] is None:
                        rec["first_piece_s"] = time.monotonic() - t0
                    rec["pieces"] += 1
                    yield piece
                if obj.get("done"):
                    for k in (
                        "prompt_eval_count",
                        "eval_count",
                        "prompt_eval_duration",
                        "eval_duration",
                        "load_duration",
                        "total_duration",
                        "done_reason",
                    ):
                        rec[k] = obj.get(k)
                    break
        rec["wall_s"] = time.monotonic() - t0

    def generate(
        self, prompt: str, *, temperature: float = 0.0, seed: int | None = None
    ) -> Iterator[str]:
        return self.chat([{"role": "user", "content": prompt}], temperature=temperature, seed=seed)


class CachedQueryEmbedder:
    """Query vectors precomputed in the `prepare` phase, so no embedding model is loaded while an
    LLM runs. Unknown query -> loud failure, never a silent fallback."""

    def __init__(self, vectors: dict[str, list[float]]):
        self.cfg, self.vectors = CONFIG, vectors

    def embed_query(self, text: str) -> list[float]:
        if text not in self.vectors:
            raise KeyError(f"query embedding not prepared: {text!r}")
        return self.vectors[text]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("documents are never embedded here")


def prepare_query_vectors(questions: list[dict]) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if QEMB_CACHE.exists():
        cache = json.loads(QEMB_CACHE.read_text())
    todo = [q["question"] for q in questions if q["question"] not in cache]
    if todo:
        emb = OllamaEmbedder(CONFIG, base_url=OLLAMA)
        for t in todo:
            cache[t] = emb.embed_query(t)
        QEMB_CACHE.parent.mkdir(parents=True, exist_ok=True)
        QEMB_CACHE.write_text(json.dumps(cache))
        unload(CONFIG.model)
    return cache


# ----------------------------------------------------------------------------- one question
def load_questions() -> list[dict]:
    allq = {}
    with open(QUESTIONS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                allq[r["id"]] = r
    return [allq[i] for i in SELECTION]


def refusal_correct(q: dict, status: str, answer: str) -> bool:
    refused = status == "refused"
    beh = q["expected_behavior"]
    if beh == "refuse":
        return refused
    if beh == "correct_premise":
        markers = PREMISE_MARKERS.get(q["id"], [])
        return (not refused) and all(m in answer.lower() for m in markers)
    return not refused  # answer / ignore_injection_and_answer


def run_agent_question(agent: Agent, llm: MeteredLLM, q: dict, gold: dict) -> dict[str, Any]:
    llm.calls.clear()
    t0 = time.monotonic()
    ttft: float | None = None
    route: RouteDecided | None = None
    retrieved: list[str] = []
    gate: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    prompt_chars = 0
    n_sources = 0
    final: Final | None = None
    drafts: dict[int, list[str]] = {}
    for ev in agent.ask(q["question"]):
        if isinstance(ev, RouteDecided):
            route = ev
        elif isinstance(ev, RetrievalResults) and not retrieved:
            retrieved = ev.chunk_ids
            gate = ev.gate.model_dump()
        elif isinstance(ev, EnrichedQuery):
            prompt_chars, n_sources = ev.prompt_chars, len(ev.sources)
        elif isinstance(ev, AnswerToken):
            drafts.setdefault(ev.attempt, []).append(ev.text)
            if ttft is None:
                ttft = time.monotonic() - t0
        elif isinstance(ev, CitationCheck):
            checks.append(
                {
                    "attempt": ev.attempt,
                    "ok": ev.ok,
                    "action": ev.action,
                    "problems": ev.problems[:5],
                    "verbatim": [c.verbatim for c in ev.citations],
                }
            )
        elif isinstance(ev, Final):
            final = ev
    total = time.monotonic() - t0
    assert final is not None
    cited = [c.anchor.chunk_id for c in final.citations]
    cited_spans = [
        (c.anchor.story, c.anchor.char_start, c.anchor.char_end) for c in final.citations
    ]
    answerable = q["answerable"]
    gold_chunks = set(gold["chunks"])
    ev_tok = sum(c.get("eval_count") or 0 for c in llm.calls)
    ev_ns = sum(c.get("eval_duration") or 0 for c in llm.calls)
    selfcheck = (
        "not_run (refused before the LLM)"
        if not llm.calls
        else "verified"
        if final.status == "answered"
        else "partial"
        if final.status == "partial"
        else "failed"
        if checks and not checks[-1]["ok"]
        else "model_declined"
    )
    return {
        "id": q["id"],
        "category": q["category"],
        "lang": q["lang"],
        "question": q["question"],
        "expected_answer": q["expected_answer"],
        "expected_behavior": q["expected_behavior"],
        "mode": "agent",
        "route": route.routes if route else None,
        "route_tools_wanted": route.tools if route else None,
        "retrieved_chunks": retrieved,
        "retrieved_has_gold": bool(gold_chunks & set(retrieved)) if answerable else None,
        "gate": gate,
        "llm_called": bool(llm.calls),
        "llm_calls": len(llm.calls),
        "ttft_s": ttft,
        "llm_ttft_s": llm.calls[0]["first_piece_s"] if llm.calls else None,
        "total_s": total,
        "prompt_chars": prompt_chars,
        "n_sources": n_sources,
        "prompt_tokens": [c.get("prompt_eval_count") for c in llm.calls],
        "num_ctx_used": llm.num_ctx,
        "tokens_generated": ev_tok,
        "tokens_per_s": ev_tok / ev_ns * 1e9 if ev_tok and ev_ns else None,
        "truncated_by_num_predict": any(c.get("done_reason") == "length" for c in llm.calls),
        "status": final.status,
        "answered": final.status != "refused",
        "refusal_code": final.refusal_code,
        "verified": final.verified,
        "selfcheck": selfcheck,
        "selfcheck_events": checks,
        "attempts": final.attempts,
        "cited_chunks": cited,
        "cited_in_gold_chunk": bool(set(cited) & gold_chunks) if answerable else None,
        "cited_overlaps_gold_span": (
            any(
                s == gs and a < ge and gstart < b
                for s, a, b in cited_spans
                for gs, gstart, ge in gold["spans"]
            )
            if answerable
            else None
        ),
        "coverage": coverage(q["expected_answer"], final.answer) if answerable else None,
        "refusal_correct": refusal_correct(q, final.status, final.answer),
        "answer": final.answer,
        "raw_drafts": {str(k): "".join(v) for k, v in drafts.items()},
    }


def run_bare_question(llm: MeteredLLM, q: dict, gold: dict) -> dict[str, Any]:
    llm.calls.clear()
    t0 = time.monotonic()
    ttft: float | None = None
    parts: list[str] = []
    for tok in llm.chat(
        [{"role": "user", "content": q["question"]}], temperature=TEMPERATURE, seed=SEED
    ):
        if ttft is None:
            ttft = time.monotonic() - t0
        parts.append(tok)
    text = "".join(parts).strip()
    call = llm.calls[0]
    ev_tok, ev_ns = call.get("eval_count") or 0, call.get("eval_duration") or 0
    declined = bool(_REFUSE_PHRASES.search(text))
    beh = q["expected_behavior"]
    markers = PREMISE_MARKERS.get(q["id"], [])
    if beh == "refuse":
        behaves = declined
    elif beh == "correct_premise":
        behaves = all(m in text.lower() for m in markers)
    else:
        behaves = not declined
    return {
        "id": q["id"],
        "category": q["category"],
        "lang": q["lang"],
        "question": q["question"],
        "expected_answer": q["expected_answer"],
        "expected_behavior": beh,
        "mode": "bare",
        "ttft_s": ttft,
        "total_s": time.monotonic() - t0,
        "prompt_tokens": [call.get("prompt_eval_count")],
        "tokens_generated": ev_tok,
        "tokens_per_s": ev_tok / ev_ns * 1e9 if ev_tok and ev_ns else None,
        "truncated_by_num_predict": call.get("done_reason") == "length",
        "declined_auto": declined,
        "coverage": coverage(q["expected_answer"], text) if q["answerable"] else None,
        "behaves_auto": behaves,
        "answer": text,
    }


# ----------------------------------------------------------------------------- driver
def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", model)


def jsonl_path(stamp: str, name: str) -> Path:
    return RESULTS / f"answers-{stamp}-{name}.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # torn last line
    return out


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_chunks_by_story() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                out.setdefault(c["story"], []).append(c)
    return out


def warm_up(llm: MeteredLLM) -> float:
    t0 = time.monotonic()
    for _ in llm.chat([{"role": "user", "content": "Say OK."}], temperature=0.0, seed=SEED):
        break
    llm.calls.clear()
    return time.monotonic() - t0


def run_model(stamp: str, model: str, think: bool, questions, golds, vectors) -> None:
    path = jsonl_path(stamp, slug(model))
    done = {r["id"] for r in read_jsonl(path)}
    todo = [q for q in questions if q["id"] not in done]
    if not todo:
        log(f"{model}: complete, skipping")
        return
    assert running_models() == [], f"another model is loaded: {running_models()}"
    llm = MeteredLLM(model, think)
    log(f"{model}: warm-up (load) ...")
    load_s = warm_up(llm)
    log(f"{model}: loaded in {load_s:.1f}s; {len(todo)} questions")
    with Store(DB, CONFIG) as store:
        retriever = HybridRetriever(store, CachedQueryEmbedder(vectors), **RRF)
        agent = Agent(llm, retriever, None, None, AgentConfig(idf_chunks=str(CHUNKS)))
        for q in todo:
            llm.num_ctx = NUM_CTX
            rec = run_agent_question(agent, llm, q, golds[q["id"]])
            need_big = any(
                (p or 0) + (rec["tokens_generated"] // max(rec["llm_calls"], 1)) > NUM_CTX
                for p in rec["prompt_tokens"]
            )
            if need_big:
                log(
                    f"{model} {q['id']}: prompt needs more than {NUM_CTX} ctx, rerunning at {NUM_CTX_BIG}"
                )
                llm.num_ctx = NUM_CTX_BIG
                rec = run_agent_question(agent, llm, q, golds[q["id"]])
                rec["ctx_rerun"] = True
            rec["model"], rec["think"], rec["load_s"] = model, think, load_s
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log(
                f"{model} {q['id']} {rec['category']}: {rec['status']} verified={rec['verified']} "
                f"total={rec['total_s']:.1f}s tok={rec['tokens_generated']} cov={rec['coverage']}"
            )
    unload(model)


def run_bare(stamp: str, model: str, think: bool, questions, golds) -> None:
    path = jsonl_path(stamp, f"BARE-{slug(model)}")
    done = {r["id"] for r in read_jsonl(path)}
    todo = [q for q in questions if q["id"] not in done]
    if not todo:
        return
    assert running_models() == [], f"another model is loaded: {running_models()}"
    llm = MeteredLLM(model, think)
    warm_up(llm)
    for q in todo:
        rec = run_bare_question(llm, q, golds[q["id"]])
        rec["model"], rec["think"] = model, think
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log(
            f"BARE {model} {q['id']}: declined_auto={rec['declined_auto']} tok={rec['tokens_generated']}"
        )
    unload(model)


def mean(xs: list[float | None]) -> float | None:
    v = [x for x in xs if x is not None]
    return statistics.fmean(v) if v else None


def composite(rows: list[dict]) -> float:
    """Selection rule for the bare baseline: mean of (behaviour correct, answerable coverage,
    verified-answer rate on answerable). Equal weights, crude, stated in the summary."""
    beh = mean([1.0 if r["refusal_correct"] else 0.0 for r in rows]) or 0.0
    cov = mean([r["coverage"] for r in rows if r["coverage"] is not None]) or 0.0
    ans = [r for r in rows if r["coverage"] is not None]
    ver = mean([1.0 if r["status"] == "answered" else 0.0 for r in ans]) or 0.0
    return (beh + cov + ver) / 3


def f(x: float | None, nd: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def pct(xs: list[bool]) -> str:
    return f"{sum(xs)}/{len(xs)}" if xs else "n/a"


def summarize(stamp: str, models: list[str]) -> Path:
    data = {m: read_jsonl(jsonl_path(stamp, slug(m))) for m in models}
    data = {m: r for m, r in data.items() if r}
    bare = {}
    for p in sorted(RESULTS.glob(f"answers-{stamp}-BARE-*.jsonl")):
        rows = read_jsonl(p)
        if rows:
            bare[rows[0]["model"]] = rows
    L: list[str] = [f"# Answer-model check ({stamp})", ""]
    L += [
        "Real `Agent` (retrieval-only path: no graph, no MCP tools) over `data/index/db.sqlite`; "
        "hybrid RRF k=30, weights bm25:vec 0.5:1, OR mode, agent defaults (top_k 4, rank_full, 60-word windows, 1200-token budget); 12 fixed golden questions "
        f"({', '.join(SELECTION)}); num_ctx {NUM_CTX} (reruns at {NUM_CTX_BIG} flagged), "
        f"num_predict {NUM_PREDICT}, temperature {TEMPERATURE}, seed {SEED}; qwen3 `think` off. "
        "CPU-only host (see the timing caveat).",
        "",
        "## Per-model means (n=12)",
        "",
        "| model | gate-refused (no LLM) | behaviour correct | answered+verified / answerable | "
        "partial | coverage (answerable) | cites gold chunk / answerable | cites gold span | "
        "TTFT s (end-to-end) | total s | tokens | tok/s | prompt tok | cut at 300 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m, rows in data.items():
        ans = [r for r in rows if r["coverage"] is not None]
        llm_rows = [r for r in rows if r["llm_called"]]
        pt = [max(p for p in r["prompt_tokens"] if p) for r in llm_rows if any(r["prompt_tokens"])]
        L.append(
            f"| {m} | {sum(not r['llm_called'] for r in rows)}/{len(rows)} "
            f"| {pct([r['refusal_correct'] for r in rows])} "
            f"| {pct([r['status'] == 'answered' for r in ans])} "
            f"| {sum(r['status'] == 'partial' for r in rows)} "
            f"| {f(mean([r['coverage'] for r in ans]), 2)} "
            f"| {pct([bool(r['cited_in_gold_chunk']) for r in ans])} "
            f"| {pct([bool(r['cited_overlaps_gold_span']) for r in ans])} "
            f"| {f(mean([r['ttft_s'] for r in llm_rows]))} | {f(mean([r['total_s'] for r in rows]))} "
            f"| {f(mean([r['tokens_generated'] for r in llm_rows]), 0)} "
            f"| {f(mean([r['tokens_per_s'] for r in llm_rows]))} "
            f"| {f(mean(pt), 0)} | {sum(r['truncated_by_num_predict'] for r in rows)} |"
        )
    L += [
        "",
        "TTFT, total s, tokens, tok/s and prompt tokens are means over the questions where the LLM "
        "was called (total s over all 12). `behaviour correct` = expected_behavior vs actual "
        "(answer: not refused; refuse: refused; correct_premise: not refused and the corrected "
        "entity is named). `answered+verified` = status `answered` (every claim cited with a "
        "verbatim quote, self-check passed).",
        "",
        "## Per category (cells: behaviour correct / n; mean coverage on answerable; "
        "verified-answered / n)",
        "",
    ]
    cats = list(dict.fromkeys(r["category"] for rows in data.values() for r in rows))
    L += ["| category | " + " | ".join(data) + " |", "|---|" + "---|" * len(data)]
    for c in cats:
        cells = []
        for rows in data.values():
            sub = [r for r in rows if r["category"] == c]
            cov = mean([r["coverage"] for r in sub if r["coverage"] is not None])
            cells.append(
                f"{sum(r['refusal_correct'] for r in sub)}/{len(sub)}; cov {f(cov, 2)}; "
                f"ver {sum(r['status'] == 'answered' for r in sub)}/{len(sub)}"
            )
        L.append(f"| {c} | " + " | ".join(cells) + " |")
    L += ["", "## Per question (status / coverage / total s)", ""]
    L += [
        "| id | category | expected | " + " | ".join(data) + " |",
        "|---|---|---|" + "---|" * len(data),
    ]
    for qid in SELECTION:
        row = [f"{qid}"]
        any_r = next((r for rows in data.values() for r in rows if r["id"] == qid), None)
        row += [any_r["category"] if any_r else "", any_r["expected_behavior"] if any_r else ""]
        for rows in data.values():
            r = next((x for x in rows if x["id"] == qid), None)
            row.append(
                "-"
                if r is None
                else f"{r['status']}{'' if r['llm_called'] else '*'} / {f(r['coverage'], 2)} / {f(r['total_s'], 0)}"
            )
        L.append("| " + " | ".join(row) + " |")
    L += [
        "",
        "`*` = refused by the retrieval gate before any LLM call (identical for every model).",
        "",
    ]
    if data:
        best = max(data, key=lambda m: composite(data[m]))
        L += [
            f"Best model by `composite` (mean of behaviour-correct rate, answerable coverage, "
            f"verified-answered rate on answerable; equal weights): **{best}** "
            f"({', '.join(f'{m} {composite(r):.2f}' for m, r in data.items())}).",
            "",
        ]
    if bare:
        L += ["## Bare LLM baseline (same question, no retrieval, no system prompt)", ""]
        for m, rows in bare.items():
            agent_rows = {r["id"]: r for r in data.get(m, [])}
            L += [
                f"Model: {m}. `declined_auto` is a regex over the answer (crude); the judgement "
                "of fabrication is in the notes below, from reading each answer.",
                "",
                "| id | category | expected | bare: declined (auto) | bare coverage | agent status | "
                "agent behaviour ok | bare answer (first 160 chars) |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for r in rows:
                a = agent_rows.get(r["id"])
                snippet = r["answer"].replace("\n", " ").replace("|", "/")[:160]
                L.append(
                    f"| {r['id']} | {r['category']} | {r['expected_behavior']} | {r['declined_auto']} "
                    f"| {f(r['coverage'], 2)} | {a['status'] if a else 'n/a'} "
                    f"| {a['refusal_correct'] if a else 'n/a'} | {snippet} |"
                )
            risky = [r for r in rows if r["category"] in ("out-of-corpus", "adversarial")]
            L += [
                "",
                f"On out-of-corpus + adversarial ({len(risky)} questions) the bare model behaved "
                f"as required (auto) on {sum(r['behaves_auto'] for r in risky)}/{len(risky)}; the "
                f"agent: {sum(a['refusal_correct'] for a in (agent_rows.get(r['id']) for r in risky) if a)}"
                f"/{len(risky)}.",
                "",
            ]
    notes = RESULTS / f"answers-{stamp}-notes.md"
    L += ["## Reading notes (answers read by hand)", ""]
    L += [notes.read_text(encoding="utf-8")] if notes.exists() else ["(not written yet)"]
    L += [
        "",
        "## Caveats",
        "",
        "- n=12 questions per model, one run each (temperature 0, seed 42): differences of one "
        "question are noise. Per-category cells hold 1-2 questions.",
        "- Key-fact coverage is a crude proxy: share of stemmed content words (3+ letters, stop "
        "words removed) of `expected_answer` that occur in the answer text with citations "
        "stripped. It rewards paraphrase-free echoes and punishes correct paraphrases and "
        "translations (the Russian question: expected answer is Russian, an English answer scores low).",
        "- No human judging of answer correctness: only the 4 answers per model read by hand "
        "(notes above) plus the mechanical self-check. `verified` means quotes are verbatim in the "
        "sources and lexically support the claim, not that the claim is true.",
        "- Golden set is agent-written and not human-reviewed (eval/golden/README.md).",
        "- Gold overlap uses chunks touching the gold quotes; a correct answer from another chunk "
        "or story passage counts as a miss. `cites gold span` is the stricter character-level test.",
        "- Timing is from a CPU-only Ollama (size_vram 0); the first LLM call per model is preceded "
        "by a warm-up so load time is not in the per-question numbers. TTFT is end-to-end (routing "
        "+ retrieval + prefill + first token); total s covers retries.",
        "- The retrieval gate (min_score, min_support) refuses before any LLM call, so its "
        "decisions are model independent; thresholds are provisional (backlog R-13).",
        "- Graph and MCP tools are off: alibi/contradiction questions get text retrieval only, "
        "so this is not a test of the neuro-symbolic layer.",
        "",
    ]
    out = RESULTS / f"answers-{stamp}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--models", nargs="*", default=[m for m, _ in MODELS])
    ap.add_argument("--pause", type=float, default=45.0)
    ap.add_argument("--bare", default="auto", help="model for the bare baseline, 'auto' or 'none'")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--only", nargs="*", help="question ids (smoke test); default: all 12")
    a = ap.parse_args(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    think = dict(MODELS)
    models = a.models
    if not a.summary_only:
        questions = [q for q in load_questions() if not a.only or q["id"] in a.only]
        by_story = load_chunks_by_story()
        golds = {q["id"]: gold_for(q, by_story) for q in questions}
        bad = {k: g["missing_quotes"] for k, g in golds.items() if g["missing_quotes"]}
        assert not bad, f"gold quotes not found: {bad}"
        log(f"stamp {a.stamp}; ollama loaded: {running_models()}")
        for m in running_models():
            unload(m)
        vectors = prepare_query_vectors(questions)
        for i, m in enumerate(models):
            if i:
                log(f"pause {a.pause:.0f}s")
                time.sleep(a.pause)
            run_model(a.stamp, m, think.get(m, False), questions, golds, vectors)
        data = {m: read_jsonl(jsonl_path(a.stamp, slug(m))) for m in models}
        data = {m: r for m, r in data.items() if len(r) == len(questions)}
        if a.bare != "none" and data:
            best = max(data, key=lambda m: composite(data[m])) if a.bare == "auto" else a.bare
            log(f"bare baseline for {best}")
            time.sleep(a.pause)
            run_bare(a.stamp, best, think.get(best, False), questions, golds)
    out = summarize(a.stamp, models)
    log(f"summary: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
