#!/usr/bin/env python3
"""'Before the reveal' test: can the agent name the culprit when the text that names him is gone?

    flock /tmp/db-llm.lock uv run python eval/pre_reveal.py            # real stack, Ollama
    uv run python scripts/eval/validate_pre_reveal.py                  # the cases, no Ollama

Cases: eval/pre_reveal/cases.jsonl (new questions, NOT in eval/golden; the frozen split is
untouched). Each case has a cut_char: the offset in data/clean/<story>.txt just before the passage
that names the culprit or explains the solution.

Conditions, the same questions, the same product agent (AgentConfig defaults of the app, generator
pinned as in eval/run_eval.py):
  full   the whole corpus. Control: the answer is in the text.
  cut    the corpus restricted to the story prefix before cut_char for that story; every other story
         untouched. Chunks and sentences that reach past the cut (chunks that straddle it too) are
         dropped; the ranks are recomputed over what is left, as if the index had been built
         without them (CutRetriever). The graph and the rule tools are NOT cut: a case whose
         question routes to them (graph_query / tool_call events) is reported as unscored.
  bare   the bare model, no retrieval (may know the stories by heart: that is what it shows).
Outcome per question: named (all keywords of one keyword set in the answer text or its cited
quotes), refused, wrong (answered, culprit not named). Wilson 95 % intervals, n in every cell.
The bare model is scored twice: with the same strict keywords, and with the looser free_keywords
(names and plain words, which also occur before the cut and so cannot be used for the agent).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "scripts" / "spike", ROOT / "eval"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import metrics as M  # noqa: E402
import run_eval as RE  # noqa: E402

from detective_board.agent import Agent  # noqa: E402
from detective_board.agent.backends import HybridRetriever, SentenceResult  # noqa: E402
from detective_board.retrieval import Hit, bm25_search, rrf_fuse, vector_search  # noqa: E402
from detective_board.retrieval.sentences import (  # noqa: E402
    RRF_K,
    RRF_WEIGHTS,
    SentenceHit,
    sentence_bm25,
    sentence_vector,
)

CASES = ROOT / "eval" / "pre_reveal" / "cases.jsonl"
RESULTS = ROOT / "docs" / "spike" / "results"
CONDITIONS = ("full", "cut", "bare")
MAX_VEC_K = 4000  # sqlite-vec limits k to 4096
GRAPH_EVENTS = ("graph_query", "graph_results", "tool_call", "tool_result")
NOTE = (
    "The cases are AI-written (reveal passages located by reading the text, keywords chosen so that "
    "no sentence and no chunk before the cut holds them together: scripts/eval/validate_pre_reveal.py). "
    "A 'named' needs the keywords in the answer text or its cited quotes, not a human reading."
)


# ----------------------------------------------------------------------------- the restriction


class CutRetriever:
    """The product retriever on an index that lacks everything past the cut of the cut stories.

    `cuts` maps story -> cut_char. A chunk is dropped when its char_end is past the cut (a chunk
    that straddles the cut is dropped too); a sentence is dropped with its chunk (so also when the
    sentence itself ends before the cut but its chunk does not). Other stories are untouched. The
    arms are searched over the whole index, filtered, cut to the same candidate counts as the
    product uses and fused again, so ranks and RRF scores are those of an index built without the
    dropped text (bm25 scores differ by the changed collection statistics; ranks hardly do).
    """

    def __init__(self, inner: HybridRetriever, cuts: dict[str, int]) -> None:
        self.inner, self.cuts = inner, dict(cuts)

    def _kept(self, story: str, char_end: int) -> bool:
        cut = self.cuts.get(story)
        return cut is None or char_end <= cut

    def search(self, query: str, limit: int) -> list[Hit]:
        inner = self.inner
        n = min(MAX_VEC_K, inner.store.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        cand = inner.kw.get("candidates", 50)
        arms = {
            "bm25": bm25_search(inner.store, query, n),
            "vec": vector_search(inner.store, inner.embedder, query, n),
        }
        arms = {
            a: [h for h in hs if self._kept(h.story, h.char_end)][:cand] for a, hs in arms.items()
        }
        return rrf_fuse(arms, k=inner.kw.get("k", 60), weights=inner.kw.get("weights"), limit=limit)

    def sentence_search(self, query: str, k: int) -> SentenceResult | None:
        inner = self.inner
        if inner.sentences is None:
            return None
        db = inner.store.db
        n = min(MAX_VEC_K, inner.sentences.count())
        qv = inner.embedder.embed_query(query)
        raw = {
            "bm25": sentence_bm25(inner.sentences, query, n),
            "vec": sentence_vector(inner.sentences, qv, n),
        }
        chunk_of: dict[int, str] = {}
        ends: dict[str, tuple[str, int] | None] = {}

        def keep(h: Hit) -> bool:
            rid = int(h.chunk_id)
            if rid not in chunk_of:
                row = inner.sentences.db.execute(
                    "SELECT chunk_id FROM sent WHERE id=?", (rid,)
                ).fetchone()
                chunk_of[rid] = row["chunk_id"]
            cid = chunk_of[rid]
            if cid not in ends:
                c = db.execute(
                    "SELECT story, char_end FROM chunks WHERE chunk_id=?", (cid,)
                ).fetchone()
                ends[cid] = None if c is None else (c["story"], c["char_end"])
            e = ends[cid]
            return e is not None and self._kept(*e)

        arms = {a: [h for h in hs if keep(h)][: inner.sentence_candidates] for a, hs in raw.items()}
        fused = rrf_fuse(arms, k=RRF_K, weights=RRF_WEIGHTS, limit=k)
        hits: list[SentenceHit] = []
        chunks: dict[str, Hit] = {}
        for h in fused:
            rid = int(h.chunk_id)
            cid = chunk_of[rid]
            hits.append(
                SentenceHit(rid, cid, h.story, h.char_start, h.char_end, h.text, h.score, h.ranks, h.scores)
            )  # fmt: skip
            if cid not in chunks:
                r = db.execute(
                    "SELECT chunk_id, story, char_start, char_end, text FROM chunks WHERE chunk_id=?",
                    (cid,),
                ).fetchone()
                chunks[cid] = Hit(
                    r["chunk_id"], r["story"], r["char_start"], r["char_end"], 0.0, text=r["text"]
                )
        return SentenceResult(hits, chunks)


# ----------------------------------------------------------------------------- scoring


def _find(kw: str, text: str) -> bool:
    return re.search(r"(?<![A-Za-z])" + re.escape(kw), text, re.IGNORECASE) is not None


def keyword_sets(case: dict, free: bool = False) -> list[list[str]]:
    if free:
        return case.get("free_keywords") or [case["truth_keywords"]]
    return [case["truth_keywords"], *case.get("truth_keywords_alt", [])]


def names_culprit(case: dict, answer: str, quotes: list[str], free: bool = False) -> bool:
    text = answer + "\n" + "\n".join(quotes)
    return any(all(_find(k, text) for k in kws) for kws in keyword_sets(case, free))


def outcome(case: dict, row: dict, free: bool = False) -> str:
    """named | refused | wrong | error | unscored (the cut run used the graph or the rule tools)."""
    if row.get("error"):
        return "error"
    if row.get("graph_used") and row["condition"] == "cut":
        return "unscored"
    if row["status"] == "refused":
        return "refused"
    quotes = [c.get("quote", "") for c in row.get("citations", [])]
    return "named" if names_culprit(case, row.get("answer", ""), quotes, free) else "wrong"


# ----------------------------------------------------------------------------- running


def run_agent(agent: Agent, question: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    first = None
    retrieved: list[str] = []
    routes: list[str] = []
    graph_used = False
    final = None
    for ev in agent.ask(question):
        if ev.type == "retrieval_results" and not retrieved:
            retrieved = [h.chunk_id for h in sorted(ev.hits, key=lambda h: h.rank)]
        elif ev.type == "route_decided":
            routes = list(ev.routes)
        elif ev.type in GRAPH_EVENTS:
            graph_used = True
        elif ev.type == "answer_token" and first is None:
            first = time.perf_counter()
        elif ev.type == "final":
            final = ev
    end = time.perf_counter()
    if final is None:
        raise RuntimeError("the agent ended without a final event")
    return {
        "status": final.status,
        "answer": final.answer,
        "citations": [
            {"n": c.n, "chunk_id": c.anchor.chunk_id, "quote": c.quote} for c in final.citations
        ],
        "refusal_code": final.refusal_code,
        "retrieved": retrieved,
        "routes": routes,
        "graph_used": graph_used,
        "ttft_s": round((first or end) - t0, 3),
        "total_s": round(end - t0, 3),
    }


def run_case(stack: RE.Stack, case: dict, condition: str) -> dict[str, Any]:
    row: dict[str, Any] = {"id": case["id"], "story": case["story"], "condition": condition}
    try:
        if condition == "bare":
            r = RE.run_bare(stack.llm, {"question": case["question"]}, {})
            r.pop("retrieved", None)
            row.update(r)
        else:
            agent = stack.agents["hybrid+graph"]
            if condition == "cut":
                cut = CutRetriever(
                    stack.retrievers["hybrid+graph"], {case["story"]: case["cut_char"]}
                )
                agent = Agent(
                    stack.llm,
                    cut,  # type: ignore[arg-type]  # same duck type as HybridRetriever
                    graph=agent.graph,
                    tools=agent.tools,
                    config=agent.cfg,
                    translate_llm=stack.llm,
                )
            row.update(run_agent(agent, case["question"]))
    except Exception as exc:  # one broken question must not lose the run
        row.update(error=f"{type(exc).__name__}: {exc}", status="error", answer="")
    row["outcome"] = outcome(case, row)
    if condition == "bare":
        row["outcome_free"] = outcome(case, row, free=True)
    return row


# ----------------------------------------------------------------------------- reporting


def summarise(rows: list[dict], cases: dict[str, dict], conditions: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cond in conditions:
        rs = [r for r in rows if r["condition"] == cond]
        scored = [r for r in rs if r["outcome"] not in ("unscored", "error")]
        n = len(scored)
        s: dict[str, Any] = {
            "n_questions": len(rs),
            "n_scored": n,
            "unscored": sum(r["outcome"] == "unscored" for r in rs),
            "errors": sum(r["outcome"] == "error" for r in rs),
        }
        for key in ("named", "refused", "wrong"):
            s[key] = M.share(sum(r["outcome"] == key for r in scored), n)
        if cond == "bare":
            free = [r for r in rs if r["outcome_free"] not in ("unscored", "error")]
            s["named_free_keywords"] = M.share(
                sum(r["outcome_free"] == "named" for r in free), len(free)
            )
        times = [r["total_s"] for r in rs if "total_s" in r]
        s["latency_s"] = (
            {
                "median": round(statistics.median(times), 1),
                "mean": round(statistics.fmean(times), 1),
                "max": round(max(times), 1),
            }
            if times
            else None
        )
        s["by_story"] = {
            st: {
                "named": sum(r["outcome"] == "named" for r in rs if r["story"] == st),
                "n": sum(1 for r in rs if r["story"] == st),
            }
            for st in sorted({r["story"] for r in rs})
        }
        out[cond] = s
    return out


def _pct(s: dict) -> str:
    if s["value"] is None:
        return "n/a (n=0)"
    lo, hi = s["ci95"]
    return f"{s['k']}/{s['n']} = {100 * s['value']:.0f} % [{100 * lo:.0f}, {100 * hi:.0f}]"


def _clip(text: str, n: int = 230) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def render_md(meta: dict, summary: dict, rows: list[dict], cases: dict[str, dict]) -> str:
    L = [f"# Pre-reveal test, {meta['date']}", "", NOTE, ""]
    L += [
        f"- commit `{meta['git_sha'][:7]}`{' (dirty tree)' if meta['git_dirty'] else ''}, "
        f"generator `{meta['generator']}`, seed {meta['seed']}, temperature {meta['temperature']}, "
        f"machine {meta['machine']}",
        f"- cases: {meta['cases_file']} (sha256 {meta['cases_sha256'][:12]}), {meta['n_cases']} questions "
        f"in {meta['n_stories']} stories; AgentConfig = the app defaults (full dict in the JSON)",
        f"- graph present: {meta['presence'].get('graph')}, sentence index: "
        f"{meta['presence'].get('sentence_index')}, rule tools: {meta['presence'].get('rule_tools')}",
        "",
        "## Result (n = questions; Wilson 95 % interval)",
        "",
        "| condition | n scored | culprit named | refused | answered wrong | median latency |",
        "|---|---|---|---|---|---|",
    ]
    labels = {
        "full": "A. full corpus (control)",
        "cut": "B. corpus cut before the reveal",
        "bare": "C. bare model, no retrieval",
    }
    for cond, s in summary.items():
        lat = f"{s['latency_s']['median']} s" if s["latency_s"] else "n/a"
        extra = f" ({s['unscored']} unscored)" if s["unscored"] else ""
        L.append(
            f"| {labels[cond]} | {s['n_scored']}/{s['n_questions']}{extra} | {_pct(s['named'])} | "
            f"{_pct(s['refused'])} | {_pct(s['wrong'])} | {lat} |"
        )
    if "bare" in summary:
        L += [
            "",
            f"Bare model with the looser `free_keywords` (names and plain words): "
            f"{_pct(summary['bare']['named_free_keywords'])}.",
        ]
    L += [
        "",
        "## Per question",
        "",
        "| id | cond | outcome | routes | answer (clipped) |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        L.append(
            f"| {r['id']} | {r['condition']} | {r['outcome']}"
            f"{'/' + r['outcome_free'] if r.get('outcome_free') not in (None, r['outcome']) else ''}"
            f" | {','.join(r.get('routes', []))} | {_clip(r.get('answer', '') or r.get('error', ''))} |".replace(
                "\n", " "
            )
        )
    L += ["", "## Cases", ""]
    seen: set[str] = set()
    for c in cases.values():
        if c["story"] in seen:
            continue
        seen.add(c["story"])
        L.append(
            f"- **{c['story']}** (cut at {c['cut_char']}): {c['rationale']} Truth: {c['truth']}"
        )
    return "\n".join(L) + "\n"


def git_sha() -> tuple[str, bool]:
    sha, dirty = RE.git_state()
    return sha, dirty


def run(args: argparse.Namespace) -> dict[str, Any]:
    cases_all = [json.loads(x) for x in Path(args.cases).read_text().splitlines() if x.strip()]
    cases = cases_all[: args.limit] if args.limit else cases_all
    conditions = [c for c in args.conditions.split(",") if c]
    for c in conditions:
        if c not in CONDITIONS:
            raise SystemExit(f"unknown condition {c!r}; choose from {CONDITIONS}")
    stack = RE.build_stack(short=False, vector_min_score=RE.VECTOR_MIN_SCORE)
    rows: list[dict] = []
    try:
        for case in cases:
            for cond in conditions:
                row = run_case(stack, case, cond)
                rows.append(row)
                if not args.quiet:
                    print(
                        f"{case['id']:<18} {cond:<5} {row['outcome']:<9} "
                        f"{row.get('total_s', 0):>6.1f}s  {_clip(row.get('answer', ''), 90)}",
                        flush=True,
                    )
    finally:
        stack.close()
    by_id = {c["id"]: c for c in cases}
    sha, dirty = git_sha()
    agent_cfg = stack.identity["agent"]
    meta = {
        "date": args.date,
        "git_sha": sha,
        "git_dirty": dirty,
        "generator": RE.GENERATOR,
        "seed": agent_cfg["seed"],
        "temperature": agent_cfg["temperature"],
        "agent_config": agent_cfg,
        "machine": stack.machine,
        "presence": stack.presence,
        "data": stack.identity["data"],
        "cases_file": str(Path(args.cases).relative_to(ROOT))
        if Path(args.cases).is_relative_to(ROOT)
        else str(args.cases),
        "cases_sha256": hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(),
        "n_cases": len(cases),
        "n_stories": len({c["story"] for c in cases}),
        "conditions": conditions,
        "note": NOTE,
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return {
        "meta": meta,
        "summary": summarise(rows, by_id, conditions),
        "rows": rows,
        "cases": by_id,
    }


def write(result: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"pre-reveal-{result['meta']['date']}"
    j, m = stem.with_suffix(".json"), stem.with_suffix(".md")
    j.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m.write_text(
        render_md(result["meta"], result["summary"], result["rows"], result["cases"]),
        encoding="utf-8",
    )
    return [j, m]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument(
        "--conditions", default=",".join(CONDITIONS), help="comma list of full,cut,bare"
    )
    ap.add_argument("--limit", type=int, default=0, help="first N cases only (smoke test)")
    ap.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    result = run(args)
    for p in write(result, Path(args.out)):
        print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
