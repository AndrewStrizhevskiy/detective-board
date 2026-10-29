#!/usr/bin/env python3
"""Suspect board before the reveal: collect model artifacts, then score them without any model.

    # on the GPU server (Ollama running); resumable through the response cache
    uv run python eval/suspects_run.py collect --split dev --out data/cache/suspects/dev.json
    # anywhere, no model; thresholds are tuned on dev only
    uv run python eval/suspects_run.py score data/cache/suspects/dev.json --lam 1 --min-support 2

Cases: eval/suspects/cases.jsonl (AI-written, to be human-checked), split in eval/suspects/split.json
(fixed before any run; run `--split test` once). Methods: evidence cards + matrix, long-context LLM,
bare LLM, and three non-LLM baselines (random, most mentioned, most accused by suspicion words).
Outcomes per case: correct, cleared_accused (a person the story clears), other_wrong, abstain.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from detective_board.extract.llm import OllamaClient  # noqa: E402
from detective_board.suspects import NO_PERSON  # noqa: E402
from detective_board.suspects import cards as cards_mod  # noqa: E402
from detective_board.suspects import fulltext as ft_mod  # noqa: E402
from detective_board.suspects import matrix as matrix_mod  # noqa: E402
from detective_board.suspects.candidates import (  # noqa: E402
    TITLES,
    build_candidates,
    mask_candidates,
    mask_text,
)
from detective_board.suspects.common import (  # noqa: E402
    KV,
    load_cases,
    load_split,
    pre_cut_chunks,
    sentences,
    story_text,
    wilson,
)

SUSPICION = re.compile(
    r"\b(suspect\w*|arrest\w*|accus\w*|guilty|murder\w*|charged|committed|killed|blame\w*|"
    r"culprit|crime|criminal)\b",
    re.I,
)


# ----------------------------------------------------------------------------- name matching
def core(name: str) -> set[str]:
    toks = [t.strip(".").lower() for t in re.findall(r"[A-Za-z][A-Za-z.'’-]*", name)]
    return {t for t in toks if t not in TITLES}


def name_match(a: str, b: str) -> bool:
    ca, cb = core(a), core(b)
    return bool(ca and cb and (ca <= cb or cb <= ca))


def is_in(name: str, targets: list[str]) -> bool:
    return any(name_match(name, t) for t in targets)


def judge(case: dict, top: str | None) -> str:
    """correct | cleared_accused | other_wrong | abstain"""
    if top is None:
        return "abstain"
    if top == NO_PERSON:
        return "correct" if case["culprit_kind"] == "non_human" else "other_wrong"
    if is_in(top, case["culprit_names"]):
        return "correct"
    if is_in(top, case["cleared_names"]):
        return "cleared_accused"
    return "other_wrong"


def culprit_rank(case: dict, order: list[str]) -> int | None:
    for i, n in enumerate(order):
        if judge(case, n) == "correct":
            return i
    return None


# ----------------------------------------------------------------------------- collect
def collect(args) -> None:
    cases = load_cases()
    split = load_split()
    if args.split != "all":
        cases = [c for c in cases if c["story"] in split[args.split]]
    if args.only:
        cases = [c for c in cases if c["story"] in args.only]
    db = sqlite3.connect(str(args.graph))
    client = OllamaClient(host=args.host, timeout=3600.0, keep_alive="30m")
    out = {"params": vars(args) | {"graph": str(args.graph)}, "cases": {}}
    cdir = Path(args.cache_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    cache = KV(cdir / "responses.sqlite")
    for case in cases:
        cs = build_candidates(db, case["story"], case["cut_char"], case["question"])
        open_c = copy.deepcopy(cs)
        masked_c = copy.deepcopy(cs)
        mask_candidates(masked_c)
        chunks = pre_cut_chunks(case["story"], case["cut_char"])
        text = story_text(case["story"])[: case["cut_char"]]
        art: dict = {
            "case": case,
            "candidates": [
                {"name": c.name, "mentions": c.mentions, "label_masked": m.label}
                for c, m in zip(open_c, masked_c, strict=True)
            ],
            "chunks": len(chunks),
            "baselines": baselines(case, open_c, chunks),
            "methods": {},
        }
        label_to_name = {m.label: c.name for c, m in zip(open_c, masked_c, strict=True)}
        label_to_name[NO_PERSON] = NO_PERSON
        for variant in args.variants:
            masked = variant == "masked"
            cands = masked_c if masked else open_c
            name_of = (lambda x, m=label_to_name: m.get(x, x)) if masked else (lambda x: x)
            if "cards" in args.methods:
                cards, stats = cards_mod.all_cards(
                    client, cache, model=args.model, question=case["question"], cands=cands,
                    chunks=chunks, masked=masked, samples=args.samples, workers=args.workers,
                )  # fmt: skip
                art["methods"][f"cards_{variant}"] = {
                    "stats": stats,
                    "cards": [
                        {"chunk_id": c.chunk_id, "candidate": name_of(c.candidate),
                         "effect": c.effect, "kind": c.kind, "quote": c.quote}
                        for c in cards
                    ],
                }  # fmt: skip
            if "fulltext" in args.methods:
                shown = mask_text(text, cands) if masked else text
                r = ft_mod.rank_fulltext(
                    client, cache, model=args.model, question=case["question"], cands=cands,
                    text=shown, num_ctx=args.num_ctx,
                )  # fmt: skip
                art["methods"][f"fulltext_{variant}"] = {
                    "order": [name_of(x) for x in r.order], "confidence": r.confidence,
                    "grounded_quotes": r.grounded_quotes, "quotes": r.quotes,
                }  # fmt: skip
        if "bare" in args.methods:
            r = ft_mod.rank_bare(
                client, cache, model=args.model, question=case["question"], cands=open_c
            )
            art["methods"]["bare"] = {"order": r.order, "confidence": r.confidence}
        out["cases"][case["id"]] = art
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print(
            f"[{len(out['cases'])}/{len(cases)}] {case['story']} cands={len(cs)} chunks={len(chunks)}",
            flush=True,
        )


def baselines(case: dict, cands, chunks) -> dict:
    by_mentions = sorted(cands, key=lambda c: -c.mentions)
    acc = {c.name: 0 for c in cands}
    for ch in chunks:
        for a, b in sentences(ch.text):
            s = ch.text[a:b]
            if SUSPICION.search(s):
                for c in cands:
                    if c.matches(s):
                        acc[c.name] += 1
    by_acc = sorted(cands, key=lambda c: (-acc[c.name], -c.mentions))
    return {
        "most_mentioned": [c.name for c in by_mentions],
        "most_accused": [c.name for c in by_acc if acc[c.name] > 0]
        or [c.name for c in by_mentions],
        "n_options": len(cands) + 1,
    }


# ----------------------------------------------------------------------------- score
def method_outputs(art: dict, p) -> dict[str, tuple[list[str], str | None]]:
    """method -> (ranking, top-or-None when abstaining)."""
    outs: dict[str, tuple[list[str], str | None]] = {}
    b = art["baselines"]
    outs["most_mentioned"] = (
        b["most_mentioned"],
        b["most_mentioned"][0] if b["most_mentioned"] else None,
    )
    outs["most_accused"] = (b["most_accused"], b["most_accused"][0] if b["most_accused"] else None)
    names = [c["name"] for c in art["candidates"]] + [NO_PERSON]
    for key, m in art["methods"].items():
        if key.startswith("cards_"):
            cards = [
                cards_mod.Card(c["chunk_id"], c["candidate"], c["effect"], c["kind"], c["quote"])
                for c in m["cards"]
            ]
            v = matrix_mod.build(cards, names, lam=p.lam, kind_bonus=p.kind_bonus,
                                 min_support=p.min_support, margin=p.margin)  # fmt: skip
            outs["matrix_" + key[6:]] = ([r.candidate for r in v.rows], v.top)
        elif key.startswith("fulltext_") or key == "bare":
            top = m["order"][0] if m["order"] else None
            if m["confidence"] == "low" and p.abstain_low:
                top = None
            outs[key] = (m["order"], top)
    for v in ("masked", "open"):
        mx, fx = outs.get("matrix_" + v), outs.get("fulltext_" + v)
        if mx and fx:
            agree = fx[1] is not None and fx[1] == mx[1]
            outs["ens_agree_" + v] = (fx[0], fx[1] if agree else None)
            top = fx[1] or mx[1]
            outs["ens_either_" + v] = (fx[0] if fx[1] else mx[0], top)
    return outs


def tally(rows: list[tuple[dict, list[str], str | None]]) -> dict:
    n = len(rows)
    out = [judge(c, top) for c, _, top in rows]
    k = lambda x: sum(1 for o in out if o == x)  # noqa: E731
    top3 = sum(1 for c, order, _ in rows if (r := culprit_rank(c, order)) is not None and r < 3)
    answered = n - k("abstain")
    return {
        "n": n,
        "correct_first": [k("correct"), wilson(k("correct"), n)],
        "culprit_in_top3": [top3, wilson(top3, n)],
        "abstain": [k("abstain"), wilson(k("abstain"), n)],
        "cleared_accused": [k("cleared_accused"), wilson(k("cleared_accused"), n)],
        "other_wrong": [k("other_wrong"), wilson(k("other_wrong"), n)],
        "wrong_total": [
            k("cleared_accused") + k("other_wrong"),
            wilson(k("cleared_accused") + k("other_wrong"), n),
        ],
        "answered": answered,
        "precision_when_answered": round(k("correct") / answered, 3) if answered else None,
    }


def reachable(case: dict, art: dict) -> bool:
    if case["culprit_kind"] == "non_human":
        return True
    return any(is_in(c["name"], case["culprit_names"]) for c in art["candidates"])


def score(args) -> None:
    data = json.loads(Path(args.artifacts).read_text())
    per_method: dict[str, list] = {}
    per_case = {}
    for cid, art in data["cases"].items():
        case = art["case"]
        outs = method_outputs(art, args)
        outs["random"] = ([], None)
        per_case[cid] = {
            "reachable": reachable(case, art),
            "n_options": art["baselines"]["n_options"],
        }
        for m, (order, top) in outs.items():
            per_method.setdefault(m, []).append((case, order, top, per_case[cid]["reachable"]))
            per_case[cid][m] = {"top": top, "outcome": judge(case, top)}
    report = {
        "params": {k: v for k, v in vars(args).items() if k != "artifacts"},
        "methods": {},
        "cases": per_case,
    }
    for m, rows in per_method.items():
        if m == "random":
            continue
        report["methods"][m] = {
            "all": tally([(c, o, t) for c, o, t, _ in rows]),
            "reachable": tally([(c, o, t) for c, o, t, r in rows if r]),
        }
    # random baseline in expectation: uniform over candidates plus NO_PERSON
    exp = {"n": len(per_case), "correct_first": 0.0, "wrong_total": 0.0}
    for art in data["cases"].values():
        case, n_opt = art["case"], art["baselines"]["n_options"]
        names = [c["name"] for c in art["candidates"]] + [NO_PERSON]
        good = sum(1 for x in names if judge(case, x) == "correct")
        exp["correct_first"] += good / n_opt
        exp["wrong_total"] += 1 - good / n_opt
    report["methods"]["random"] = {
        "expected": {k: round(v, 2) if isinstance(v, float) else v for k, v in exp.items()}
    }
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if args.report:
        Path(args.report).write_text(text)
    print_table(report)


def print_table(report: dict) -> None:
    print(
        f"{'method':22} {'n':>3} {'1st':>4} {'top3':>5} {'abst':>5} {'clr-acc':>8} {'wrong':>6}   (all cases | reachable)"
    )
    for m, v in report["methods"].items():
        if "all" not in v:
            e = v["expected"]
            print(
                f"{m:22} {e['n']:>3} {e['correct_first']:>4} {'':>5} {'':>5} {'':>8} {e['wrong_total']:>6}   expected value"
            )
            continue
        for scope in ("all", "reachable"):
            t = v[scope]
            print(
                f"{m + (' [R]' if scope == 'reachable' else ''):22} {t['n']:>3} {t['correct_first'][0]:>4} {t['culprit_in_top3'][0]:>5} {t['abstain'][0]:>5} {t['cleared_accused'][0]:>8} {t['wrong_total'][0]:>6}"
            )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    c.add_argument("--only", nargs="*")
    c.add_argument("--graph", type=Path, default=ROOT / "data" / "graph" / "graph.sqlite")
    c.add_argument("--host", default="http://localhost:11434")
    c.add_argument("--model", default="qwen3:8b")
    c.add_argument("--methods", nargs="+", default=["cards", "fulltext", "bare"])
    c.add_argument("--variants", nargs="+", default=["masked"], choices=["masked", "open"])
    c.add_argument("--samples", type=int, default=3)
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--num-ctx", type=int, default=20480)
    c.add_argument("--cache-dir", default=str(ROOT / "data" / "cache" / "suspects"))
    c.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("artifacts")
    s.add_argument("--lam", type=float, default=1.0)
    s.add_argument("--kind-bonus", type=float, default=0.5)
    s.add_argument("--min-support", type=int, default=2)
    s.add_argument("--margin", type=float, default=1.0)
    s.add_argument("--abstain-low", action=argparse.BooleanOptionalAction, default=True)
    s.add_argument("--report")
    args = ap.parse_args()
    collect(args) if args.cmd == "collect" else score(args)


if __name__ == "__main__":
    main()
