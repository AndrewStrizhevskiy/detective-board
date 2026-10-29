"""Neuro-symbolic R3 on the DEV contradiction cases (23): candidate pairs from the graph, judged by a
small model from the two quotes. Matched to each case's own involved claims (unlike run_eval).

    uv run python eval/r3_semantic.py --mode pairs            # no model: candidate recall only
    flock /tmp/db-llm.lock uv run python eval/r3_semantic.py --mode judge --max-pairs 12

The TEST ids of eval/golden/split.json are refused: the case file is filtered to the dev ids
before anything else is read, and `refuse_test_ids` stops the run if a test id is asked for.
The model's verdict is a hypothesis, never a rule verdict (docs/symbolic-layer.md 11.5).
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT / "eval"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import metrics as M  # noqa: E402

from detective_board.agent.llm import LLM, OllamaLLM  # noqa: E402
from detective_board.agent.semantic_r3 import (  # noqa: E402
    JUDGE_VERSION,
    Judged,
    Statement,
    candidate_pairs,
    entity_names,
    judge_pairs,
    load_statements,
    person_terms,
)
from detective_board.agent.window import content_words  # noqa: E402
from detective_board.graph import GraphStore  # noqa: E402

CONTRADICTIONS = ROOT / "eval" / "golden" / "contradictions.jsonl"
SPLIT = ROOT / "eval" / "golden" / "split.json"
GRAPH = ROOT / "data" / "graph" / "graph.sqlite"
RESULTS = ROOT / "docs" / "spike" / "results"
MATCH_COVERAGE = 0.6  # share of the shorter word set that the other one holds
MODEL = "qwen3:4b-instruct"
NOTE = (
    "Dev split only (23 cases, tuned on dev: optimistic). A positive is found when a pair judged "
    "`contradicts` has BOTH quotes matching two different involved claims of the case "
    "(strict) or at least one (loose); matching = content-word coverage >= 0.6 of the shorter "
    "side. A control is a false positive when any pair among its judged pairs is judged "
    "`contradicts`. The model verdict is a hypothesis, not a rule verdict. Gold sets are AI-written."
)


def _split() -> dict[str, list[str]]:
    return json.loads(SPLIT.read_text())["content"]["contradictions"]


def refuse_test_ids(ids: list[str], split: dict[str, list[str]] | None = None) -> None:
    """Stop the run when a test id is asked for, or an id is not a dev id."""
    sp = split or _split()
    bad = [i for i in ids if i in set(sp["test"])]
    if bad:
        raise SystemExit(f"refused: test-split ids must not be run or scored here: {bad}")
    unknown = [i for i in ids if i not in set(sp["dev"])]
    if unknown:
        raise SystemExit(f"refused: not dev ids: {unknown}")


def dev_cases(ids: list[str] | None = None, path: Path = CONTRADICTIONS) -> list[dict[str, Any]]:
    sp = _split()
    want = ids or list(sp["dev"])
    refuse_test_ids(want, sp)
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] in set(want):  # test rows are never kept
            out.append(row)
    return out


def matches(quote: str, involved: str) -> bool:
    a, b = content_words(quote), content_words(involved)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= MATCH_COVERAGE


def match_count(a: Statement, b: Statement, case: dict[str, Any]) -> int:
    """How many of the pair's two statements match DIFFERENT involved claims of the case (0..2)."""
    inv = [c["quote"] for c in case["involved_claims"]]
    ia = {i for i, q in enumerate(inv) if matches(a.quote, q)}
    ib = {i for i, q in enumerate(inv) if matches(b.quote, q)}
    if ia and ib and (len(ia | ib) >= 2):
        return 2
    return 1 if (ia or ib) else 0


def case_persons(store: GraphStore, case: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for c in case["involved_claims"]:
        try:
            found = store.resolve(c["who"], story=case["story"], kinds=("person",))
        except Exception:  # noqa: BLE001 - an unknown name is simply not resolved
            found = []
        ids += [p for p in found if p not in ids]
    return ids


def run_case(
    store: GraphStore, case: dict[str, Any], llm: LLM | None, max_pairs: int, use_persons: bool
) -> dict[str, Any]:
    t0 = time.monotonic()
    story = case["story"]
    conn = store.conn
    persons = case_persons(store, case) if use_persons else []
    pairs = candidate_pairs(
        load_statements(conn, story),
        persons=persons,
        person_names=person_terms(conn, persons),
        entities=entity_names(conn, story),
        max_pairs=max_pairs,
    )
    t_pairs = time.monotonic() - t0
    cand = [match_count(p.a, p.b, case) for p in pairs]
    judged: list[Judged] = judge_pairs(llm, pairs) if llm is not None else []
    contra = [j for j in judged if j.verdict == "contradicts"]
    row: dict[str, Any] = {
        "id": case["id"],
        "story": story,
        "kind": case["kind"],
        "expected": bool(case["expected_finding"]),
        "persons": persons,
        "pairs": len(pairs),
        "cand_strict": any(m == 2 for m in cand),
        "cand_loose": any(m >= 1 for m in cand),
        "judged": len(judged),
        "invalid": sum(1 for j in judged if j.verdict is None),
        "contradicts": len(contra),
        "any_contradicts": bool(contra),
        "strict": any(match_count(j.pair.a, j.pair.b, case) == 2 for j in contra),
        "loose": any(match_count(j.pair.a, j.pair.b, case) >= 1 for j in contra),
        "seconds_pairs": round(t_pairs, 2),
        "seconds": round(time.monotonic() - t0, 2),
        "contradicting_pairs": [
            {
                "a": [j.pair.a.speaker, j.pair.a.quote],
                "b": [j.pair.b.speaker, j.pair.b.quote],
                "match": match_count(j.pair.a, j.pair.b, case),
            }
            for j in contra
        ],
    }
    return row


def summarise(rows: list[dict[str, Any]], judged: bool) -> dict[str, Any]:
    pos = [r for r in rows if r["expected"]]
    ctl = [r for r in rows if not r["expected"]]
    out: dict[str, Any] = {
        "positives": len(pos),
        "controls": len(ctl),
        "baseline_recall_automatic_facts": M.share(0, len(pos)),
        "candidate_recall_strict": M.share(sum(r["cand_strict"] for r in pos), len(pos)),
        "candidate_recall_loose": M.share(sum(r["cand_loose"] for r in pos), len(pos)),
        "pairs_per_case_mean": round(sum(r["pairs"] for r in rows) / max(len(rows), 1), 2),
        "seconds_total": round(sum(r["seconds"] for r in rows), 1),
    }
    if judged:
        out |= {
            "recall_strict": M.share(sum(r["strict"] for r in pos), len(pos)),
            "recall_loose": M.share(sum(r["loose"] for r in pos), len(pos)),
            "false_positives_any": M.share(sum(r["any_contradicts"] for r in ctl), len(ctl)),
            "invalid_answers": sum(r["invalid"] for r in rows),
            "judged_total": sum(r["judged"] for r in rows),
        }
    return out


def render(meta: dict[str, Any], summ: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    def f(s: dict[str, Any]) -> str:
        lo, hi = s["ci95"]
        v = "-" if s["value"] is None else f"{s['value']:.2f}"
        return f"{v} [{lo:.2f}, {hi:.2f}] ({s['k']}/{s['n']})"

    L = [
        f"# R3 semantic, dev split ({meta['mode']}, {meta['judge_version']})",
        "",
        f"- {meta['date']}, git `{meta['git_sha']}`, model `{meta['model']}`, max pairs {meta['max_pairs']}, "
        f"person filter {meta['use_persons']}, host {meta['machine']}",
        f"- {NOTE}",
        "",
        "| measure | value |",
        "|---|---|",
        f"| baseline recall on automatic facts (rules) | {f(summ['baseline_recall_automatic_facts'])} |",
        f"| candidate recall, strict (no model) | {f(summ['candidate_recall_strict'])} |",
        f"| candidate recall, loose (no model) | {f(summ['candidate_recall_loose'])} |",
    ]
    if "recall_strict" in summ:
        L += [
            f"| recall matched to the case, strict | {f(summ['recall_strict'])} |",
            f"| recall matched to the case, loose | {f(summ['recall_loose'])} |",
            f"| controls with any `contradicts` (false positives) | {f(summ['false_positives_any'])} |",
            f"| invalid model answers | {summ['invalid_answers']} of {summ['judged_total']} |",
        ]
    L += [
        f"| pairs per case (mean) | {summ['pairs_per_case_mean']} |",
        f"| seconds, all cases | {summ['seconds_total']} |",
        "",
        "| case | kind | exp | pairs | cand s/l | contradicts | strict | loose | s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        L.append(
            f"| {r['id']} | {r['kind'].split('_')[0]} | {int(r['expected'])} | {r['pairs']} | "
            f"{int(r['cand_strict'])}/{int(r['cand_loose'])} | {r['contradicts']} | "
            f"{int(r['strict'])} | {int(r['loose'])} | {r['seconds']} |"
        )
    return "\n".join(L) + "\n"


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None, llm: LLM | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--mode", choices=("pairs", "judge"), default="pairs")
    ap.add_argument("--max-pairs", type=int, default=12)
    ap.add_argument("--ids", nargs="*", help="dev ids only; test ids are refused")
    ap.add_argument("--no-persons", action="store_true", help="story-wide pairs, no person filter")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", type=Path, default=RESULTS)
    ap.add_argument("--graph", type=Path, default=GRAPH)
    a = ap.parse_args(argv)
    cases = dev_cases(a.ids)
    if a.mode == "judge" and llm is None:
        llm = OllamaLLM(a.model, keep_alive="30m", num_ctx=2048)
    # a private copy: GraphStore may migrate, and the shared data is never touched
    tmp = tempfile.mkdtemp(prefix="r3sem-")
    shutil.copy(a.graph, Path(tmp) / "graph.sqlite")
    store = GraphStore(str(Path(tmp) / "graph.sqlite"))
    try:
        rows = [
            run_case(store, c, llm if a.mode == "judge" else None, a.max_pairs, not a.no_persons)
            for c in cases
        ]
    finally:
        store.close()
    meta = {
        "mode": a.mode,
        "judge_version": JUDGE_VERSION,
        "model": a.model if a.mode == "judge" else "-",
        "max_pairs": a.max_pairs,
        "use_persons": not a.no_persons,
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "git_sha": _sha(),
        "machine": platform.node(),
        "split": "dev",
        "case_ids": [c["id"] for c in cases],
    }
    summ = summarise(rows, a.mode == "judge")
    a.out.mkdir(parents=True, exist_ok=True)
    stem = f"r3-semantic-dev-{a.mode}{('-' + a.tag) if a.tag else ''}"
    (a.out / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "summary": summ, "rows": rows}, indent=1, ensure_ascii=False)
    )
    (a.out / f"{stem}.md").write_text(render(meta, summ, rows))
    print(render(meta, summ, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
