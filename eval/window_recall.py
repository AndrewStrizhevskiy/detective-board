#!/usr/bin/env python3
"""Offline window recall: does best_window() on the gold chunk keep the gold quote? (no Ollama)

For every answerable question of eval/golden/questions.jsonl, eval/spike_questions.jsonl and
eval/spike_questions_hard.jsonl, each gold chunk (quotes mapped to chunks by overlap with
data/clean/<story>.txt, as scripts/spike/chunk_gold.py does) is windowed with the question. A quote
is kept when the window contains it or overlaps >= 50% of it. A question counts when ANY of its
gold quotes is kept in some gold chunk. Usage: uv run python eval/window_recall.py [--words 110 150]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))

from chunk_gold import find_spans, load_questions  # noqa: E402

from detective_board.agent.window import best_window, idf_from_chunks  # noqa: E402


def load() -> tuple[list[dict], list[dict]]:
    chunks = [json.loads(x) for x in (ROOT / "data/chunks.jsonl").read_text().splitlines()]
    qs = load_questions(
        ROOT / "eval/spike_questions.jsonl", ROOT / "eval/spike_questions_hard.jsonl"
    )
    for r in map(json.loads, (ROOT / "eval/golden/questions.jsonl").read_text().splitlines()):
        if r["answerable"] and r["gold_quotes"]:
            qs.append(
                {
                    "id": r["id"],
                    "lang": r["lang"],
                    "group": "golden",
                    "question": r["question"],
                    "quotes": [(g["story"], g["quote"]) for g in r["gold_quotes"]],
                }
            )
    return chunks, qs


def recall(chunks: list[dict], qs: list[dict], words: int, idf: dict | None) -> dict[str, list]:
    clean: dict[str, str] = {}
    out: dict[str, list] = {}
    for q in qs:
        hit = False
        for story, quote in q["quotes"]:
            if story not in clean:
                clean[story] = (ROOT / "data/clean" / f"{story}.txt").read_text()
            for s, e in find_spans(clean[story], quote):
                for c in chunks:
                    if c["story"] != story or not (c["char_start"] < e and s < c["char_end"]):
                        continue
                    w = best_window(c["text"], q["question"], words, idf)
                    a, b = c["char_start"] + w.start, c["char_start"] + w.end
                    lo, hi = max(s, c["char_start"]), min(e, c["char_end"])  # quote part in chunk
                    if min(hi, b) - max(lo, a) >= 0.5 * (hi - lo):
                        hit = True
        out.setdefault(q["lang"], []).append(hit)
        out.setdefault("all", []).append(hit)
        out.setdefault(q["group"], []).append(hit)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--words", type=int, nargs="+", default=[110, 150])
    a = ap.parse_args()
    chunks, qs = load()
    idf = idf_from_chunks([c["text"] for c in chunks], [c["story"] for c in chunks])
    for words in a.words:
        for name, table in (("lexical", None), ("idf", idf)):
            r = recall(chunks, qs, words, table)
            cells = "  ".join(
                f"{k} {sum(v)}/{len(v)}={sum(v) / len(v):.0%}" for k, v in sorted(r.items())
            )
            print(f"window_words={words:<4} {name:<8} {cells}")


if __name__ == "__main__":
    main()
