#!/usr/bin/env python3
"""Helpers for scripts/server_gold12.sh (no Ollama needed).

chunks [--out data/cache/gold12.jsonl]     the 12 gold chunks as an extract.run --chunks file
slug MODEL PROMPT_PATH                     run label, e.g. qwen3_4b__extract_v2_1
report --stamp S OUT.jsonl [OUT.jsonl ..]  score the runs, print one table, write
                                           docs/spike/results/gold12-<S>.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "spike"))

GOLD_DIR = ROOT / "eval" / "extraction_gold"
CHUNKS = ROOT / "data" / "chunks.jsonl"
DEFAULT_OUT = ROOT / "data" / "cache" / "gold12.jsonl"
RESULTS_DIR = ROOT / "docs" / "spike" / "results"


def build_chunks(gold_dir: Path, chunks_path: Path, out: Path) -> list[dict]:
    """One record per gold file. The text comes from data/chunks.jsonl when that file has the
    chunk (the extraction cache key hashes the text, so it must be the corpus text); the gold
    file's own copy is the fallback, with a warning when the two differ."""
    corpus: dict[str, dict] = {}
    if chunks_path.exists():
        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    corpus[rec["chunk_id"]] = rec
    recs = []
    for f in sorted(gold_dir.glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        cid = g["chunk_id"]
        c = corpus.get(cid)
        if c is None:
            print(
                f"warning: {cid} not in {chunks_path}; using the gold file's text", file=sys.stderr
            )
        elif c["text"] != g["text"]:
            print(
                f"warning: {cid}: gold text differs from the corpus; using the corpus",
                file=sys.stderr,
            )
        recs.append({"chunk_id": cid, "story": g.get("story", ""), "text": (c or g)["text"]})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8"
    )
    return recs


def slug(model: str, prompt: str) -> str:
    clean = lambda s: re.sub(r"[^A-Za-z0-9.]+", "_", s).strip("_")  # noqa: E731
    return f"{clean(model)}__{clean(Path(prompt).stem)}"


def report(stamp: str, outputs: list[Path], results_dir: Path = RESULTS_DIR) -> Path:
    import score_pipeline as sp

    gold = sp.se.load_gold(GOLD_DIR)
    rows = {p.stem: sp.score_results(gold, sp.load_results(p)) for p in outputs}
    print(sp.format_text(rows))
    md = results_dir / f"gold12-{stamp}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        f"# Gold-12 comparison {stamp}\n\n"
        f"Production pipeline (schema v2) on the 12 chunks of `eval/extraction_gold/`. "
        f"Scorer: `scripts/spike/score_pipeline.py`. Runs: {', '.join(rows)}.\n\n"
        f"{sp.format_markdown(rows)}\n\n"
        "json ok = status ok; usable = ok or repaired; person/place/time/deny = share of claims; "
        "in_speech/transit = share of events. "
        "The gold sets are automatically labelled (not human-checked).\n",
        encoding="utf-8",
    )
    print(f"\nwrote {md}")
    return md


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chunks")
    c.add_argument("--out", type=Path, default=DEFAULT_OUT)
    c.add_argument("--gold", type=Path, default=GOLD_DIR)
    c.add_argument("--corpus", type=Path, default=CHUNKS)
    s = sub.add_parser("slug")
    s.add_argument("model")
    s.add_argument("prompt")
    r = sub.add_parser("report")
    r.add_argument("--stamp", required=True)
    r.add_argument("outputs", type=Path, nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "chunks":
        recs = build_chunks(a.gold, a.corpus, a.out)
        print(f"{len(recs)} gold chunks -> {a.out}")
    elif a.cmd == "slug":
        print(slug(a.model, a.prompt))
    else:
        report(a.stamp, a.outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
