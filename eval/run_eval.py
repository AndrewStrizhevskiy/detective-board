#!/usr/bin/env python3
"""Eval runner: four configurations on the frozen golden split, mechanical metrics, intervals.

    uv run python eval/run_eval.py --short             # CI: 8 dev questions, fake LLM, no network
    uv run python eval/run_eval.py --split dev         # real stack: Ollama, data/index, the graph
    uv run python eval/run_eval.py --split test        # once per frozen configuration, clean tree

Configurations, the same generator (qwen3:4b-instruct, think off; ADR-0008) in all four:
  bare           the question to the model, no retrieval, no sources
  vector         bge-m3 vector search only, top-4 chunks into the agent's answer path
  vector+rerank  'not run': the repo has no local reranker (retrieval/rerank.py is a stub)
  hybrid+graph   the real agent: hybrid retrieval, sentence index, graph, rules, extractive answers
Query embeddings are computed once per question and shared by vector and hybrid+graph.

Metrics are mechanical (eval/metrics.py): behaviour correct (answerable: answered with key-fact
coverage >= 0.5; out-of-corpus: refused), citation correctness, answer-sentence hit, refusal
precision / recall and false refusals, chunk recall@k, contradiction detection on
eval/golden/contradictions.jsonl with the rules only (no LLM), latency. Wilson 95 % intervals,
exact McNemar between configurations, n in every cell. The gold sets are AI-written until issue #9
is done; every table says so.

Output: <out>/eval-<date>-<split>[-short].{json,md,svg}; json has one row per question and run,
the git SHA, whether the tree was clean, and a hash of the configuration.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "scripts" / "spike", ROOT / "eval"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import metrics as M  # noqa: E402
from chunk_gold import find_spans  # noqa: E402
from run_answer_check import _REFUSE_PHRASES, coverage, gold_for, refusal_correct  # noqa: E402

from detective_board.agent import Agent, HybridRetriever, OllamaLLM  # noqa: E402
from detective_board.api.config import ApiConfig  # noqa: E402
from detective_board.api.services import _agent_cfg, build_services  # noqa: E402

GENERATOR = "qwen3:4b-instruct"
QUESTIONS = ROOT / "eval" / "golden" / "questions.jsonl"
CONTRADICTIONS = ROOT / "eval" / "golden" / "contradictions.jsonl"
SPLIT = ROOT / "eval" / "golden" / "split.json"
CHUNKS = ROOT / "data" / "chunks.jsonl"
CLEAN = ROOT / "data" / "clean"
RESULTS = ROOT / "docs" / "spike" / "results"
RUNS = ROOT / "eval" / "runs"  # git-ignored: short runs and scratch
CONFIGS = ("bare", "vector", "vector+rerank", "hybrid+graph")
# Short mode: fixed dev questions across categories (no Russian: no translation model in CI).
SHORT_IDS = ("g001", "g007", "g016", "g022", "g028", "g038", "g047", "g056")
RECALL_K = (1, 4, 6)
COVERAGE_OK = 0.5
BARE_MAX_TOKENS = 300
GOLD_NOTE = "Gold sets are AI-written and not yet reviewed by a human (issue #9): every number is against AI labels."


# ----------------------------------------------------------------------------- inputs


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def split_ids(split: str) -> dict[str, list[str]]:
    content = json.loads(SPLIT.read_text())["content"]
    if split == "all":
        return {k: v["dev"] + v["test"] for k, v in content.items()}
    return {k: v[split] for k, v in content.items()}


def load_chunks() -> tuple[dict[str, str], dict[str, list[dict]]]:
    text: dict[str, str] = {}
    by_story: dict[str, list[dict]] = {}
    for c in read_jsonl(CHUNKS):
        text[c["chunk_id"]] = c["text"]
        by_story.setdefault(c["story"], []).append(c)
    return text, by_story


def story_texts() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(CLEAN.glob("*.txt"))}


# ----------------------------------------------------------------------------- the stack


class SharedEmbedder:
    """One query embedding per question for every configuration that retrieves."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.cfg, self.cache = inner, inner.cfg, {}

    def embed_query(self, text: str) -> list[float]:
        if text not in self.cache:
            self.cache[text] = self.inner.embed_query(text)
        return self.cache[text]

    def embed_documents(self, texts: Any) -> list[list[float]]:
        return self.inner.embed_documents(texts)


@dataclasses.dataclass
class Stack:
    llm: Any
    agents: dict[str, Agent]
    tools: Any
    graph: Any
    close: Callable[[], None]
    agent_config: dict[str, Any]
    machine: str
    chunk_text: dict[
        str, str
    ]  # the texts of the index the agents searched (citations are checked against these)

    def story_in_graph(self, story: str) -> bool:
        conn = getattr(self.graph, "conn", None)
        if conn is None:
            return False
        return (
            conn.execute("SELECT 1 FROM g_node WHERE story=? LIMIT 1", (story,)).fetchone()
            is not None
        )


def build_stack(short: bool) -> Stack:
    """Short: the API's --fake services (FakeLLM, 10-chunk fixture, fixture graph). Full: the real
    data and Ollama, the generator pinned for all configurations. The rule tools are the ones the
    app wires (stdio MCP over the graph, else in-process)."""
    from detective_board.api import fixture

    cfg = ApiConfig(fake=True) if short else ApiConfig(llm_model=GENERATOR)
    svc = build_services(cfg, with_agent=True)
    ac = _agent_cfg(cfg)
    if short:
        llm: Any = fixture.build_llm()
        store, raw_emb = fixture.build_store()  # a store and the embedder that matches it
    else:
        from detective_board.retrieval import EmbeddingConfig, OllamaEmbedder

        emb_cfg = EmbeddingConfig(
            model=cfg.embed_model,
            dim=cfg.embed_dim,
            doc_prefix=cfg.embed_doc_prefix,
            query_prefix=cfg.embed_query_prefix,
        )
        raw_emb = OllamaEmbedder(emb_cfg, base_url=cfg.ollama_host, keep_alive=cfg.keep_alive)
        llm = OllamaLLM(
            GENERATOR,
            cfg.ollama_host,
            num_ctx=cfg.num_ctx,
            keep_alive=cfg.keep_alive,
            timeout=cfg.llm_timeout_s,
        )
        store = svc.store
    emb = SharedEmbedder(raw_emb)
    vector_cfg = dataclasses.replace(ac, top_k=4, extract_top_k=4)
    agents = {
        "vector": Agent(
            llm,
            HybridRetriever(store, emb, weights={"bm25": 0.0, "vec": 1.0}),
            graph=None,
            tools=None,
            config=vector_cfg,
            translate_llm=llm,
        ),
        "hybrid+graph": Agent(
            llm,
            HybridRetriever(store, emb, sentences=svc.sentences),
            graph=svc.graph,
            tools=svc.tools,
            config=ac,
            translate_llm=llm,
        ),
    }

    def close() -> None:
        if store is not svc.store:
            store.close()
        svc.close()

    machine = f"{platform.node()} / {platform.machine()} / {platform.system()} {platform.release()}"
    texts = {
        r["chunk_id"]: r["text"] for r in store.db.execute("SELECT chunk_id, text FROM chunks")
    }
    return Stack(llm, agents, svc.tools, svc.graph, close, dataclasses.asdict(ac), machine, texts)


# ----------------------------------------------------------------------------- one question


def _row(q: dict, config: str, split: str) -> dict[str, Any]:
    return {
        "id": q["id"],
        "config": config,
        "split": split,
        "category": q["category"],
        "answerable": bool(q["answerable"]),
        "expected_behavior": q["expected_behavior"],
    }


def run_bare(llm: Any, q: dict, row: dict) -> dict:
    t0 = time.perf_counter()
    first = None
    parts: list[str] = []
    # same cap as eval/run_answer_check.py: an unbounded bare answer can run for minutes on CPU
    for tok in llm.chat(
        [{"role": "user", "content": q["question"]}],
        temperature=0.0,
        seed=42,
        num_predict=BARE_MAX_TOKENS,
    ):
        if first is None:
            first = time.perf_counter()
        parts.append(tok)
    answer = "".join(parts)
    refused = bool(_REFUSE_PHRASES.search(answer)) or not answer.strip()
    row.update(
        status="refused" if refused else "answered", answer=answer, citations=[], retrieved=[]
    )
    row.update(
        ttft_s=round((first or time.perf_counter()) - t0, 3),
        total_s=round(time.perf_counter() - t0, 3),
    )
    return row


def run_agent(agent: Agent, q: dict, row: dict) -> dict:
    t0 = time.perf_counter()
    first = None
    retrieved: list[str] = []
    final = None
    llm_called = False
    for ev in agent.ask(q["question"]):
        kind = ev.type
        if kind == "retrieval_results" and not retrieved:
            retrieved = [h.chunk_id for h in sorted(ev.hits, key=lambda h: h.rank)]
        elif kind in ("enriched_query", "answer_token"):
            llm_called = True
            if kind == "answer_token" and first is None:
                first = time.perf_counter()
        elif kind == "final":
            final = ev
    end = time.perf_counter()
    if final is None:
        raise RuntimeError("the agent ended without a final event")
    cites = [
        {"n": c.n, "chunk_id": c.anchor.chunk_id, "story": c.anchor.story, "quote": c.quote}
        for c in final.citations
    ]
    row.update(
        status=final.status,
        answer=final.answer,
        citations=cites,
        retrieved=retrieved,
        refusal_code=final.refusal_code,
        llm_called=llm_called,
    )
    row.update(ttft_s=round((first or end) - t0, 3), total_s=round(end - t0, 3))
    return row


def judge(
    row: dict, q: dict, gold: dict, chunk_text: dict[str, str], stories: dict[str, str]
) -> dict:
    """Mechanical verdicts added to a finished row."""
    if row.get("error"):
        row.update(correct=False, refused=False)
        return row
    refused = row["status"] == "refused"
    cov = coverage(q["expected_answer"], row.get("answer", "")) if q["answerable"] else None
    behaviour = refusal_correct(q, row["status"], row.get("answer", ""))
    correct = behaviour and (not q["answerable"] or (cov or 0) >= COVERAGE_OK)
    verdicts = M.citation_verdicts(row.get("citations", []), chunk_text, gold["chunks"], find_spans)
    row.update(
        refused=refused,
        coverage=None if cov is None else round(cov, 3),
        correct=bool(correct),
        citation_verdicts=verdicts,
        citations_all_correct=bool(verdicts) and all(v["correct"] for v in verdicts),
        sentence_hit=M.answer_sentence_hit(
            row.get("citations", []), stories, gold["spans"], find_spans
        )
        if q["answerable"]
        else None,
        gold_chunks=gold["chunks"],
        **{
            f"recall@{k}": M.recall_at_k(row.get("retrieved", []), gold["chunks"], k)
            for k in RECALL_K
        },
    )
    return row


# ----------------------------------------------------------------------------- contradictions


def run_contradictions(stack: Stack, items: list[dict]) -> list[dict]:
    """Rules only: find_contradictions for the people named in each case (story-wide when none is
    found in the graph). found = at least one violated finding. A story missing from the graph is
    reported as skipped, not as a miss."""
    rows = []
    for it in items:
        row = {
            "id": it["id"],
            "kind": it["kind"],
            "story": it["story"],
            "expected": bool(it["expected_finding"]),
        }
        if stack.tools is None:
            rows.append({**row, "skipped": "no rule tools (no graph)"})
            continue
        if not stack.story_in_graph(it["story"]):
            rows.append({**row, "skipped": "story not in the graph"})
            continue
        people: list[str] = []
        for claim in it.get("involved_claims", []):
            try:
                people += [
                    pid
                    for pid in stack.graph.resolve(
                        claim["who"], story=it["story"], kinds=("person",)
                    )
                    if pid not in people
                ]
            except Exception:  # noqa: BLE001 - an unknown name is simply not resolved
                pass
        calls = [{"story": it["story"], "person_id": pid} for pid in people] or [
            {"story": it["story"]}
        ]
        found, errors, rules = False, [], set()
        for args in calls:
            res = stack.tools.call("find_contradictions", args, timeout=5.0)
            if res.get("error"):
                errors.append(res["error"].get("code", "error"))
                continue
            hits = res.get("items") or res.get("findings") or []
            if hits:
                found = True
                rules |= {h.get("rule") for h in hits if isinstance(h, dict)}
        if errors and len(errors) == len(calls):
            rows.append({**row, "skipped": f"rules error: {errors[0]}"})
            continue
        rows.append(
            {**row, "found": found, "rules_found": sorted(r for r in rules if r), "people": people}
        )
    return rows


# ----------------------------------------------------------------------------- summary


def summarise(rows: list[dict], configs_run: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cfg in CONFIGS:
        if cfg not in configs_run:
            out[cfg] = {
                "status": "not run",
                "reason": "no local reranker in the repo (retrieval/rerank.py is a stub)"
                if cfg == "vector+rerank"
                else "not selected",
            }
            continue
        rs = [r for r in rows if r["config"] == cfg]
        ok = [r for r in rs if not r.get("error")]
        ans = [r for r in ok if r["answerable"]]
        answered_ans = [r for r in ans if not r["refused"]]
        verdicts = [v for r in ok for v in r.get("citation_verdicts", [])]
        cited = [r for r in answered_ans if r.get("citations")]
        s: dict[str, Any] = {
            "n": len(rs),
            "errors": len(rs) - len(ok),
            "behaviour_correct": M.share(sum(r["correct"] for r in rs), len(rs)),
            **M.refusal_counts(
                {"answerable": r["answerable"], "refused": r["refused"]} for r in ok
            ),
            "latency_median_s": {
                "ttft": round(statistics.median(r["ttft_s"] for r in ok), 3) if ok else None,
                "total": round(statistics.median(r["total_s"] for r in ok), 3) if ok else None,
            },
        }
        if cfg != "bare":
            s["citation_correct"] = M.share(sum(v["correct"] for v in verdicts), len(verdicts))
            s["answers_all_citations_correct"] = M.share(
                sum(r["citations_all_correct"] for r in cited), len(cited)
            )
            hits = [r["sentence_hit"] for r in answered_ans if r.get("sentence_hit") is not None]
            s["answer_sentence_hit"] = M.share(sum(hits), len(hits))
            for k in RECALL_K:
                vals = [r[f"recall@{k}"] for r in ok if r.get(f"recall@{k}") is not None]
                s[f"recall@{k}"] = M.share(sum(vals), len(vals))
        out[cfg] = s
    by = {
        cfg: {r["id"]: bool(r["correct"]) for r in rows if r["config"] == cfg}
        for cfg in configs_run
    }
    pairs = [(a, b) for i, a in enumerate(configs_run) for b in configs_run[i + 1 :]]
    out["paired_behaviour_correct"] = {f"{a} vs {b}": M.paired(by[a], by[b]) for a, b in pairs}
    return out


def summarise_contradictions(rows: list[dict]) -> dict[str, Any]:
    done = [r for r in rows if "found" in r]
    out = {
        "all": M.detection({"expected": r["expected"], "found": r["found"]} for r in done),
        "skipped": len(rows) - len(done),
    }
    for kind in sorted({r["kind"] for r in done}):
        out[kind] = M.detection(
            {"expected": r["expected"], "found": r["found"]} for r in done if r["kind"] == kind
        )
    return out


def fmt(s: dict | None) -> str:
    if not s or s.get("value") is None:
        return f"- (n={s['n']})" if s else "-"
    return f"{s['value']:.2f} [{s['ci95'][0]:.2f}, {s['ci95'][1]:.2f}] ({s['k']}/{s['n']})"


def render_md(meta: dict, summary: dict, contra: dict) -> str:
    cols = [
        "behaviour_correct",
        "citation_correct",
        "answers_all_citations_correct",
        "answer_sentence_hit",
        "refusal_precision",
        "refusal_recall",
        "false_refusal_rate",
        "recall@1",
        "recall@4",
        "recall@6",
    ]
    lines = [
        f"# Eval {meta['date']} ({meta['split']}{', short' if meta['short'] else ''})",
        "",
        f"> {GOLD_NOTE}",
        "",
        f"- generator: `{meta['generator']}`; machine: {meta['machine']}{' (fake LLM, fixture index: tests the wiring, not quality)' if meta['short'] else ''}",
        f"- git `{meta['git_sha']}`{' (uncommitted changes)' if meta['dirty'] else ''}; config hash `{meta['config_hash']}`; questions {meta['n_questions']}, contradiction cases {meta['n_contradictions']}",
        "- values: share [Wilson 95 % interval] (k/n); behaviour correct = answerable answered with key-fact coverage >= 0.5, out-of-corpus refused (a mechanical proxy, no judge)",
        "",
        "| metric | " + " | ".join(CONFIGS) + " |",
        "|---|" + "---|" * len(CONFIGS),
    ]
    for c in cols:
        cells = []
        for cfg in CONFIGS:
            s = summary[cfg]
            cells.append(
                s.get("status", "")
                if s.get("status") == "not run"
                else fmt(s.get(c))
                if c in s
                else "n/a"
            )
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    lat = [
        summary[c]["latency_median_s"] if "latency_median_s" in summary[c] else None
        for c in CONFIGS
    ]
    lines.append(
        "| median first token / total, s | "
        + " | ".join(f"{x['ttft']} / {x['total']}" if x else "not run" for x in lat)
        + " |"
    )
    lines.append(
        "| errors / n | "
        + " | ".join(
            f"{summary[c]['errors']}/{summary[c]['n']}" if "n" in summary[c] else "not run"
            for c in CONFIGS
        )
        + " |"
    )
    lines += [
        "",
        "Latency is measured on the machine above; it is the target-laptop number only when run there (issue #14).",
        "",
        "## Paired comparison (behaviour correct, exact McNemar)",
        "",
        "| pair | n | only first right | only second right | p |",
        "|---|---|---|---|---|",
    ]
    for pair, p in summary["paired_behaviour_correct"].items():
        lines.append(f"| {pair} | {p['n']} | {p['only_a']} | {p['only_b']} | {p['p_mcnemar']} |")
    a = contra["all"]
    lines += [
        "",
        "## Contradiction detection (rules only, no LLM)",
        "",
        f"Cases run {a['tp'] + a['fp'] + a['fn'] + a['tn']}, skipped {contra['skipped']} (story not in the graph or no tools).",
        "",
        "| kind | TP | FP | FN | TN | precision | recall | FP rate on controls |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for kind, d in contra.items():
        if kind == "skipped":
            continue
        lines.append(
            f"| {kind} | {d['tp']} | {d['fp']} | {d['fn']} | {d['tn']} | {fmt(d['precision'])} | {fmt(d['recall'])} | {fmt(d['fp_rate_controls'])} |"
        )
    lines += [
        "",
        "Not run: vector+rerank (no local reranker exists; not faked). Claim-level faithfulness needs a judge model and is not computed here.",
        "",
    ]
    return "\n".join(lines)


def render_svg(summary: dict, title: str) -> str:
    """Bar chart of behaviour correct per configuration with Wilson whiskers (plain SVG, no deps)."""
    w, h, left, top, bar = 640, 320, 60, 40, 90
    plot_h = h - top - 60
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="sans-serif" font-size="12">',
        f'<text x="{left}" y="22" font-size="14">{title}</text>',
    ]
    for i in range(0, 11, 2):
        y = top + plot_h * (1 - i / 10)
        out.append(
            f'<line x1="{left}" x2="{w - 20}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/><text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{i / 10:.1f}</text>'
        )
    for i, cfg in enumerate(CONFIGS):
        x = left + 20 + i * (bar + 50)
        s = summary[cfg]
        out.append(f'<text x="{x + bar / 2}" y="{h - 30}" text-anchor="middle">{cfg}</text>')
        bc = s.get("behaviour_correct")
        if not bc or bc.get("value") is None:
            out.append(
                f'<text x="{x + bar / 2}" y="{top + plot_h - 6}" text-anchor="middle" fill="#666">not run</text>'
            )
            continue
        y = top + plot_h * (1 - bc["value"])
        lo, hi = (top + plot_h * (1 - v) for v in bc["ci95"])
        out.append(
            f'<rect x="{x}" y="{y:.1f}" width="{bar}" height="{top + plot_h - y:.1f}" fill="#7f2318"/>'
        )
        out.append(
            f'<line x1="{x + bar / 2}" x2="{x + bar / 2}" y1="{lo:.1f}" y2="{hi:.1f}" stroke="#222" stroke-width="2"/>'
        )
        out.append(
            f'<text x="{x + bar / 2}" y="{h - 14}" text-anchor="middle" fill="#444">{bc["k"]}/{bc["n"]}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- main


def git_state() -> tuple[str, bool]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def iter_questions(ids: list[str], short: bool) -> Iterator[dict]:
    by_id = {q["id"]: q for q in read_jsonl(QUESTIONS)}
    for qid in SHORT_IDS if short else ids:
        yield by_id[qid]


def run(args: argparse.Namespace) -> dict[str, Any]:
    split = "dev" if args.short else args.split
    sha, dirty = git_state()
    if split == "test" and dirty and not args.allow_dirty:
        raise SystemExit(
            "the test split is run once per frozen configuration: commit first (or --allow-dirty for a dry run)"
        )
    ids = split_ids(split)
    questions = list(iter_questions(ids["golden"], args.short))
    items = [c for c in read_jsonl(CONTRADICTIONS) if c["id"] in set(ids["contradictions"])]
    _, by_story = load_chunks()
    stories = story_texts()
    golds = {q["id"]: gold_for(q, by_story) for q in questions}
    configs_run = [
        c for c in (args.configs or ["bare", "vector", "hybrid+graph"]) if c != "vector+rerank"
    ]
    stack = build_stack(args.short)
    chunk_text = stack.chunk_text
    rows: list[dict] = []
    try:
        for q in questions:
            for cfg in configs_run:
                row = _row(q, cfg, split)
                try:
                    if cfg == "bare":
                        run_bare(stack.llm, q, row)
                    else:
                        run_agent(stack.agents[cfg], q, row)
                except Exception as exc:  # noqa: BLE001 - one failed question is a row, not a crash
                    row.update(
                        error=f"{type(exc).__name__}: {str(exc)[:200]}", ttft_s=None, total_s=None
                    )
                rows.append(judge(row, q, golds[q["id"]], chunk_text, stories))
                if not args.quiet:
                    print(
                        f"{q['id']} {cfg:13s} {row.get('status', 'error'):9s} correct={row['correct']}",
                        flush=True,
                    )
        contra_rows = run_contradictions(stack, items)
    finally:
        stack.close()
    cfg_hash = hashlib.sha256(
        json.dumps(
            {
                "generator": GENERATOR,
                "agent": stack.agent_config,
                "configs": configs_run,
                "short": args.short,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:12]
    meta = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "split": split,
        "short": bool(args.short),
        "generator": "FakeLLM (fixture)" if args.short else GENERATOR,
        "machine": stack.machine,
        "git_sha": sha,
        "dirty": dirty,
        "config_hash": cfg_hash,
        "n_questions": len(questions),
        "n_contradictions": len(items),
        "gold_note": GOLD_NOTE,
    }
    return {
        "meta": meta,
        "summary": summarise(rows, configs_run),
        "contradictions": summarise_contradictions(contra_rows),
        "rows": rows,
        "contradiction_rows": contra_rows,
    }


def write(result: dict, out_dir: Path) -> list[Path]:
    m = result["meta"]
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"eval-{m['date']}-{m['split']}{'-short' if m['short'] else ''}"
    paths = [stem.with_suffix(".json"), stem.with_suffix(".md"), stem.with_suffix(".svg")]
    paths[0].write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n")
    paths[1].write_text(render_md(m, result["summary"], result["contradictions"]))
    paths[2].write_text(
        render_svg(
            result["summary"],
            f"Behaviour correct, {m['split']} split{' (short, fake LLM)' if m['short'] else ''}, Wilson 95 %",
        )
    )
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument(
        "--short",
        action="store_true",
        help="CI mode: 8 dev questions, fake LLM, fixture index, no network",
    )
    ap.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    ap.add_argument(
        "--configs", nargs="+", choices=CONFIGS, help="default: bare vector hybrid+graph"
    )
    ap.add_argument("--out", type=Path, help="default: eval/runs (short) or docs/spike/results")
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow a test-split run with uncommitted changes (dry run only)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    result = run(args)
    paths = write(result, args.out or (RUNS if args.short else RESULTS))
    s = result["summary"]
    print(
        f"done in {time.perf_counter() - t0:.1f} s: "
        + ", ".join(
            f"{c} {fmt(s[c].get('behaviour_correct'))}"
            for c in CONFIGS
            if s[c].get("status") != "not run"
        )
    )
    for p in paths:
        print(f"wrote {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
