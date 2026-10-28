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
Outcomes per question (Wilson 95 % intervals, n in every cell):
  culprit named (PRIMARY)  an accepted name or alias of the culprit or cause (case field
                           culprit_names) in the answer text or its cited quotes; else answered
                           wrong, or refused
  innocent accused         a cleared person's name (cleared_names) and no culprit alias
  keyword metric           secondary: reveal-text keyword sets (truth_keywords[_alt])
Rescore saved answers without the models: uv run python eval/pre_reveal.py --rescore RESULT.json
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
    "The cases are AI-written: the reveal passages were located by reading the text, the cut placed "
    "before them and checked by scripts/eval/validate_pre_reveal.py. Every outcome is lexical "
    "(names or keywords in the answer and its cited quotes), not a human reading."
)
CHUNKS = ROOT / "data" / "chunks.jsonl"
LABELS = {
    "full": "A. full corpus (control)",
    "cut": "B. corpus cut before the reveal",
    "bare": "C. bare model, no retrieval",
}
PRIMARY_NOTE = (
    "**Primary: culprit named.** An accepted name or alias of the culprit or cause (case field "
    "`culprit_names`, e.g. Turner / Black Jack, the horse, snake / adder, Cairns, suicide / killed "
    "herself) occurs in the answer text or its cited quotes, case-insensitive, at a word start. It "
    "is primary because the question asks WHO or WHAT, and a correct answer can use any wording. "
    "Its weakness: several aliases also occur long before the cut (Turner, the horse, Joseph and "
    "Harrison, Oldacre, Cunningham are characters from the start), so in condition B a 'named' can "
    "be a mere mention; the exposure table below counts the pre-cut chunks that hold an alias, and "
    "every B 'named' is read by hand in the notes.\n\n"
    "**Secondary: keyword metric.** Reveal-text keyword sets (`truth_keywords`, "
    "`truth_keywords_alt`, e.g. 'lessen his guilt', 'her own life', 'murdering their coachman'); "
    "the validator guarantees that no sentence and no chunk before the cut holds a set, so it is "
    "leak-free in B, but it is wording-bound: the full-corpus control fails it when the agent quotes "
    "a different correct sentence. That is why it is not the primary metric.\n\n"
    "**Innocent accused.** Answered, a cleared person's name (`cleared_names`: James McCarthy, "
    "Fitzroy Simpson, McFarlane, Neligan, Grace Dunbar; 5 of 8 stories) in the answer or its "
    "quotes, and no culprit alias. A lexical proxy: a mention is not an accusation, read the rows.\n\n"
    "**Bare model (C).** Names in the questions were not masked (story titles, victims), and the "
    "4B model may know the stories by heart; C measures memory and guessing, not reasoning. Its "
    "refusals are detected with the phrase list of eval/run_answer_check.py."
)
LIMITS = (
    "- n = 16 questions in 8 stories; the two questions of a story are not independent, so the "
    "intervals are optimistic. Cases and aliases are AI-written, not reviewed by a human.\n"
    "- The cut is placed by reading; the validator checks verbatim quotes, the cut before every quote "
    "and keyword leaks, but cannot check paraphrased hints or a culprit named by a description.\n"
    "- CutRetriever re-fuses the arms over the kept hits; BM25 scores still use the statistics of the "
    "full index (ranks hardly change). The chunk that straddles the cut is dropped, so up to one "
    "chunk of legitimate pre-cut text is lost per story.\n"
    "- The graph and the rule tools are not cut; no question here routed to them (no graph_query or "
    "tool_call event), otherwise the row would be 'unscored'.\n"
    "- One run, temperature 0, seed 42; the laptop CPU was shared with other jobs (serialised by "
    "flock), so latencies are indicative."
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
    """Case-insensitive; the match starts at a word boundary ('adder' does not match 'ladder')."""
    return re.search(r"(?<![A-Za-z])" + re.escape(kw), text, re.IGNORECASE) is not None


def keyword_sets(case: dict) -> list[list[str]]:
    """Secondary metric: reveal-text keywords (no sentence or chunk before the cut holds a set)."""
    return [case["truth_keywords"], *case.get("truth_keywords_alt", [])]


def answer_text(row: dict) -> str:
    """The answer and its cited quotes (an extractive answer is mostly its quotes)."""
    quotes = [c.get("quote", "") for c in row.get("citations", [])]
    return "\n".join([row.get("answer", "") or "", *quotes])


def match_sets(sets: list[list[str]], text: str) -> str | None:
    """The first set whose phrases all occur in `text`, joined with '+'; None when none does."""
    for kws in sets:
        if kws and all(_find(k, text) for k in kws):
            return "+".join(kws)
    return None


def score(case: dict, row: dict) -> dict[str, Any]:
    """Outcome fields of one finished row.

    outcome           PRIMARY: named (an accepted name or alias of the culprit or cause from
                      `culprit_names` in the answer or its cited quotes) | wrong | refused | error |
                      unscored (the cut run used the graph or the rule tools)
    outcome_keywords  secondary: the same with the reveal-text keyword sets
    innocent_accused  answered, a cleared person's name (`cleared_names`) in the answer or its
                      quotes and no culprit alias: a lexical proxy for 'names the innocent man'
    """
    out: dict[str, Any] = {
        "matched_name": None,
        "matched_keywords": None,
        "cleared_mentioned": None,
        "innocent_accused": False,
    }
    if row.get("error"):
        base = "error"
    elif row.get("graph_used") and row["condition"] == "cut":
        base = "unscored"
    elif row["status"] == "refused":
        base = "refused"
    else:
        base = None
    if base is not None:
        return {**out, "outcome": base, "outcome_keywords": base}
    text = answer_text(row)
    name = match_sets(case["culprit_names"], text)
    kw = match_sets(keyword_sets(case), text)
    cleared = match_sets([[n] for n in case.get("cleared_names", [])], text)
    return {
        "outcome": "named" if name else "wrong",
        "outcome_keywords": "named" if kw else "wrong",
        "matched_name": name,
        "matched_keywords": kw,
        "cleared_mentioned": cleared,
        "innocent_accused": bool(cleared) and not name,
    }


def outcome(case: dict, row: dict) -> str:
    """The primary outcome only (see `score`)."""
    return score(case, row)["outcome"]


def precut_exposure(case: dict, chunks: list[dict]) -> dict[str, int]:
    """Per culprit-alias set: how many chunks that end before the cut hold it. Non-zero means the
    cut corpus can 'name' the culprit by merely mentioning him (Turner is a neighbour long before
    he is the murderer), so a named in condition B must be read, not counted blindly."""
    pre = [
        c["text"]
        for c in chunks
        if c["story"] == case["story"] and c["char_end"] <= case["cut_char"]
    ]
    return {
        "+".join(s): sum(all(_find(k, t) for k in s) for t in pre) for s in case["culprit_names"]
    }


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
    row.update(score(case, row))
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
        s["innocent_accused"] = M.share(sum(bool(r["innocent_accused"]) for r in scored), n)
        s["named_keywords"] = M.share(sum(r["outcome_keywords"] == "named" for r in scored), n)
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


def render_md(
    meta: dict,
    summary: dict,
    rows: list[dict],
    cases: dict[str, dict],
    exposure: dict[str, dict[str, int]] | None = None,
) -> str:
    L = [f"# Pre-reveal test, {meta['date']}", "", NOTE, ""]
    L += [
        f"- run at commit `{meta['git_sha'][:7]}`{' (dirty tree)' if meta['git_dirty'] else ''}, "
        f"generator `{meta['generator']}`, seed {meta['seed']}, temperature {meta['temperature']}, "
        f"machine {meta['machine']}",
        f"- cases: {meta['cases_file']} (sha256 {meta['cases_sha256'][:12]} at run time), "
        f"{meta['n_cases']} questions in {meta['n_stories']} stories; AgentConfig = the app "
        "defaults (full dict in the JSON)",
        f"- graph present: {meta['presence'].get('graph')}, sentence index: "
        f"{meta['presence'].get('sentence_index')}, rule tools: {meta['presence'].get('rule_tools')}",
    ]
    rs = meta.get("rescored")
    if rs:
        L.append(
            f"- RESCORED {rs['at']} from `{rs['from']}` (the saved answers, no model rerun) at commit "
            f"`{rs['git_sha'][:7]}`, cases sha256 {rs['cases_sha256'][:12]}; supersedes the "
            "scoring of the first report"
        )
    L += [
        "",
        "## Metrics",
        "",
        PRIMARY_NOTE,
        "",
        "## Result (n = questions; Wilson 95 % interval)",
        "",
        "| condition | n scored | **culprit named** (primary) | refused | answered, culprit not "
        "named | innocent accused | keyword metric (secondary) | median latency |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cond, s in summary.items():
        lat = f"{s['latency_s']['median']} s" if s["latency_s"] else "n/a"
        extra = f" ({s['unscored']} unscored)" if s["unscored"] else ""
        L.append(
            f"| {LABELS[cond]} | {s['n_scored']}/{s['n_questions']}{extra} | {_pct(s['named'])} | "
            f"{_pct(s['refused'])} | {_pct(s['wrong'])} | {_pct(s['innocent_accused'])} | "
            f"{_pct(s['named_keywords'])} | {lat} |"
        )
    conds = list(summary)
    for i, a in enumerate(conds):
        for b in conds[i + 1 :]:
            pa = {r["id"]: r["outcome"] == "named" for r in rows if r["condition"] == a}
            pb = {r["id"]: r["outcome"] == "named" for r in rows if r["condition"] == b}
            p = M.paired(pa, pb)
            L.append(
                f"\nPaired, culprit named, {a} vs {b}: only {a} {p['only_a']}, only {b} "
                f"{p['only_b']}, exact McNemar p {p['p_mcnemar']:.3g} (n {p['n']})."
            )
    L += [
        "",
        "Per story, culprit named (questions named / asked):",
        "",
        "| story | " + " | ".join(LABELS[c] for c in summary) + " |",
        "|---|" + "---|" * len(summary),
    ]
    stories = sorted({r["story"] for r in rows})
    for st in stories:
        cells = [
            f"{summary[c]['by_story'][st]['named']}/{summary[c]['by_story'][st]['n']}"
            if st in summary[c]["by_story"]
            else "-"
            for c in summary
        ]
        L.append(f"| {st} | " + " | ".join(cells) + " |")
    if exposure:
        L += [
            "",
            "Leak exposure of the primary metric: chunks that end before the cut and hold a culprit "
            "alias (a 'named' in condition B can be a mere mention of the name):",
            "",
            "| story | alias set: pre-cut chunks |",
            "|---|---|",
        ]
        seen: set[str] = set()
        for c in cases.values():
            if c["story"] in seen:
                continue
            seen.add(c["story"])
            ex = exposure.get(c["id"], {})
            L.append(f"| {c['story']} | " + ", ".join(f"{k}: {v}" for k, v in ex.items()) + " |")
    L += [
        "",
        "## Per question",
        "",
        "| id | cond | culprit named | keywords | innocent | matched | answer (clipped) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        matched = r.get("matched_name") or ""
        if r.get("cleared_mentioned"):
            matched += f" (cleared: {r['cleared_mentioned']})"
        answer = _clip(r.get("answer", "") or r.get("error", "")).replace("|", "/")
        L.append(
            f"| {r['id']} | {r['condition']} | {r['outcome']} | {r['outcome_keywords']} | "
            f"{'yes' if r.get('innocent_accused') else ''} | {matched} | {answer} |"
        )
    L += ["", "## Cases", ""]
    seen2: set[str] = set()
    for c in cases.values():
        if c["story"] in seen2:
            continue
        seen2.add(c["story"])
        L.append(
            f"- **{c['story']}** (cut at {c['cut_char']}): {c['rationale']} Truth: {c['truth']}"
        )
    L += ["", "## Limits", "", LIMITS]
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
        "exposure": exposure_for(by_id),
    }


def exposure_for(cases: dict[str, dict]) -> dict[str, dict[str, int]]:
    chunks = [json.loads(x) for x in CHUNKS.read_text(encoding="utf-8").splitlines() if x]
    return {cid: precut_exposure(c, chunks) for cid, c in cases.items()}


def write(result: dict, out_dir: Path, suffix: str = "") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"pre-reveal-{result['meta']['date']}{suffix}"
    j, m = stem.with_suffix(".json"), stem.with_suffix(".md")
    j.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m.write_text(
        render_md(
            result["meta"],
            result["summary"],
            result["rows"],
            result["cases"],
            result.get("exposure"),
        ),
        encoding="utf-8",
    )
    return [j, m]


def rescore(result: dict, cases_path: Path, source: str) -> dict[str, Any]:
    """Score the saved rows again with the current cases file (no model call). The run's meta is
    kept; `meta.rescored` records when, from what and with which cases and code."""
    cases = {
        c["id"]: c
        for c in (json.loads(x) for x in cases_path.read_text(encoding="utf-8").splitlines() if x)
    }
    missing = sorted({r["id"] for r in result["rows"]} - set(cases))
    if missing:
        raise SystemExit(f"--rescore: cases missing for {missing}")
    rows = []
    for r in result["rows"]:
        r = {k: v for k, v in r.items() if k not in ("outcome", "outcome_free")}
        r.update(score(cases[r["id"]], r))
        rows.append(r)
    used = {r["id"]: cases[r["id"]] for r in rows}
    conditions = list(result["meta"]["conditions"])
    sha, dirty = git_sha()
    meta = {
        **result["meta"],
        "rescored": {
            "from": source,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_sha": sha,
            "git_dirty": dirty,
            "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        },
    }
    return {
        "meta": meta,
        "summary": summarise(rows, used, conditions),
        "rows": rows,
        "cases": used,
        "exposure": exposure_for(used),
    }


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
    ap.add_argument(
        "--rescore", default="", help="a saved result JSON: score its answers again, no model call"
    )
    args = ap.parse_args(argv)
    if args.rescore:
        src = Path(args.rescore)
        result = rescore(json.loads(src.read_text(encoding="utf-8")), Path(args.cases), src.name)
        for p in write(result, Path(args.out), suffix="-rescored"):
            print("wrote", p)
        return 0
    result = run(args)
    for p in write(result, Path(args.out)):
        print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
