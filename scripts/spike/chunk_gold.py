#!/usr/bin/env python3
"""Map every evidence quote to the chunk_id(s) of data/chunks.jsonl that contain it (stdlib only).

Inputs: eval/spike_questions.jsonl (evidence = str, story = expected_story) and
eval/spike_questions_hard.jsonl (evidence = list[str], story = evidence_stories[i] or expected_story).
Matching is done on data/clean/<story>.txt with whitespace-insensitive, quote-style-insensitive regex;
a chunk is gold when its [char_start, char_end) span overlaps any occurrence of the quote, so quotes
straddling a chunk boundary yield every chunk they touch. Quotes with no occurrence are reported
and the exit code is 1. Output: eval/spike_chunk_gold.json.
No network, no models.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import CHUNKS, ROOT, load_jsonl  # noqa: E402

CLEAN = ROOT / "data" / "clean"
OLD_Q = ROOT / "eval" / "spike_questions.jsonl"
HARD_Q = ROOT / "eval" / "spike_questions_hard.jsonl"
OUT = ROOT / "eval" / "spike_chunk_gold.json"


def quote_regex(quote: str) -> re.Pattern:
    parts = []
    for tok in quote.split():
        parts.append(
            "".join(
                "['‘’]" if ch in "'‘’" else '["“”]' if ch in '"“”' else re.escape(ch) for ch in tok
            )
        )
    return re.compile(r"\s+".join(parts))


def find_spans(text: str, quote: str) -> list[tuple[int, int]]:
    if not quote.split():
        return []
    return [m.span() for m in quote_regex(quote).finditer(text)]


def touching_chunks(chunks: list[dict], spans: list[tuple[int, int]]) -> list[str]:
    """chunk_ids (document order) whose char range overlaps any span."""
    out = []
    for c in chunks:
        if any(c["char_start"] < e and s < c["char_end"] for s, e in spans):
            out.append(c["chunk_id"])
    return out


def load_questions(old_path=OLD_Q, hard_path=HARD_Q) -> list[dict]:
    """Normalised questions: id, lang, group, question, expected_stories, quotes=[(story, quote)]."""
    qs = []
    for path, is_old in ((old_path, True), (hard_path, False)):
        for r in load_jsonl(path):
            if is_old:
                ev = [r["evidence"]] if isinstance(r["evidence"], str) else list(r["evidence"])
                sts = [r["expected_story"]] * len(ev)
                group = f"old-{r['lang']}"
                exp = [r["expected_story"]]
            else:
                ev = [r["evidence"]] if isinstance(r["evidence"], str) else list(r["evidence"])
                sts = r.get("evidence_stories") or [r["expected_story"]] * len(ev)
                exp = r.get("expected_stories") or [r["expected_story"]]
                group = "cross" if len(set(exp)) > 1 else "hard"
            if len(sts) != len(ev):
                raise ValueError(f"{r['id']}: evidence_stories length != evidence length")
            qs.append(
                {
                    "id": r["id"],
                    "lang": r["lang"],
                    "group": group,
                    "question": r["question"],
                    "expected_stories": exp,
                    "quotes": list(zip(sts, ev)),
                }
            )
    return qs


def build_gold(questions: list[dict], chunks: list[dict], clean_dir=CLEAN):
    by_story: dict[str, list[dict]] = {}
    for c in chunks:
        by_story.setdefault(c["story"], []).append(c)
    texts: dict[str, str] = {}
    gold, missing = {}, []
    for q in questions:
        entries, ids = [], []
        for story, quote in q["quotes"]:
            if story not in texts:
                p = clean_dir / f"{story}.txt"
                texts[story] = p.read_text(encoding="utf-8") if p.exists() else ""
            spans = find_spans(texts[story], quote)
            cids = touching_chunks(by_story.get(story, []), spans) if spans else []
            entries.append({"story": story, "quote": quote, "spans": spans, "chunks": cids})
            if not cids:
                missing.append({"id": q["id"], "story": story, "quote": quote})
            ids += [c for c in cids if c not in ids]
        gold[q["id"]] = {
            "group": q["group"],
            "expected_stories": q["expected_stories"],
            "chunks": ids,
            "quotes": entries,
        }
    return gold, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    gold, missing = build_gold(load_questions(), load_jsonl(CHUNKS))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(gold, f, ensure_ascii=False, indent=1)
    n_q = sum(len(g["quotes"]) for g in gold.values())
    multi = [k for k, g in gold.items() if any(len(e["chunks"]) > 1 for e in g["quotes"])]
    print(f"{len(gold)} questions, {n_q} quotes -> {a.out}")
    print(f"quotes touching >1 chunk (boundary straddle or repeats): {len(multi)} {multi}")
    for m in missing:
        print(f"UNMAPPED {m['id']} [{m['story']}]: {m['quote']!r}", file=sys.stderr)
    print(f"unmapped quotes: {len(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
