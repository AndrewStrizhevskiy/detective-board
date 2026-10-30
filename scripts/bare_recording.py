#!/usr/bin/env python3
"""Write bare-model recordings for the split view (issue #13) from an eval run (stdlib only).

Usage: python3 scripts/bare_recording.py --eval docs/spike/results/eval-...json --ids g001 g003 g062
Takes the `bare` rows of an eval/run_eval.py result (the question to the model, no retrieval, no
sources) and writes web/replay/bare/<id>.json: {meta, answer}. Plain text, no trace events: the
bare model has no steps to show. The answer is copied byte for byte; nothing is staged or edited.
Then run scripts/replay_index.py so the UI lists the new recording.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "replay" / "bare"
# eval/run_eval.py run_bare(): the same call for every question
CALL = "question only as the user message, no system prompt, temperature 0, seed 42, 300-token cap"


def recording(result: dict, qid: str, source: str, questions: dict[str, str]) -> dict:
    meta = result["meta"]
    rows = [r for r in result["rows"] if r.get("config") == "bare" and r.get("id") == qid]
    if len(rows) != 1:
        raise SystemExit(f"{qid}: {len(rows)} bare rows in {source}, need exactly 1")
    row = rows[0]
    if qid not in questions:
        raise SystemExit(f"{qid}: not in eval/golden/questions.jsonl")
    if not str(row.get("answer", "")).strip():
        raise SystemExit(f"{qid}: the bare answer is empty")
    return {
        "meta": {
            "label": "RECORDING",
            "kind": "bare model, no sources",
            "qid": qid,
            "question": questions[qid],
            "model": meta["generator"],
            "call": CALL,
            "recorded_on": meta["date"],
            "machine": meta["machine"],
            "git_sha": meta["git_sha"][:7],
            "config_hash": meta["config_hash"],
            "split": meta["split"],
            "ttft_s": row["ttft_s"],
            "seconds": row["total_s"],
            "source": source,
            "note": "Copied unchanged from the eval run; not chosen or edited after the run.",
        },
        "answer": row["answer"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--eval", required=True, help="an eval/run_eval.py result JSON")
    ap.add_argument("--ids", nargs="+", required=True, help="golden question ids, e.g. g001")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    path = Path(args.eval).resolve()
    result = json.loads(path.read_text(encoding="utf-8"))
    golden = ROOT / "eval" / "golden" / "questions.jsonl"
    questions = {q["id"]: q["question"] for q in map(json.loads, golden.open(encoding="utf-8"))}
    source = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for qid in args.ids:
        rec = recording(result, qid, source, questions)
        target = out / f"{qid}.json"
        target.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
