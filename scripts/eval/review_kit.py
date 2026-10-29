#!/usr/bin/env python3
"""Build the human-review kit for the AI-written gold sets (issue #9). Stdlib only.

Usage: python3 scripts/eval/review_kit.py [--out eval/review/<date>] [--date YYYY-MM-DD]
Selects the items of issue #9 (20 golden questions, 16 contradiction cases, every claim and
relation of 4 extraction chunks; the ids the issue names are always in), and writes one reading
sheet per set plus verdicts.csv. Each item comes with its source passage from data/clean and a
mechanical pre-check (is every quote verbatim, and how often). The pre-check is a script, not a
review: the verdicts are written by people, then applied with scripts/eval/apply_review.py.
Nothing in eval/golden or eval/extraction_gold is changed here. The selection is deterministic
(seeded hash), so re-running gives the same items.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "eval" / "golden" / "questions.jsonl"
CONTRA = ROOT / "eval" / "golden" / "contradictions.jsonl"
SPLIT = ROOT / "eval" / "golden" / "split.json"
EXTRACTION = ROOT / "eval" / "extraction_gold"
CLEAN = ROOT / "data" / "clean"
SEED = "gold-review-v1"

# issue #9: the ids it names; g027 joins them because the issue asks to resolve g027 vs c042
NAMED_GOLDEN = [
    "g015", "g027", "g029", "g036", "g042", "g045", "g054", "g055",
    "g056", "g059", "g061", "g062", "g063", "g064",
]  # fmt: skip
NAMED_CONTRA = ["c003", "c004", "c006", "c007", "c024", "c028", "c033", "c041", "c042", "c043"]
N_GOLDEN, N_CONTRA, N_TEST_EXTRA = 20, 16, 6
# the testimony and time chunks: the kind of text the rules read (README table of eval/extraction_gold)
CHUNKS = [
    "boscombe-valley-mystery-0007",
    "silver-blaze-0004",
    "reigate-squires-0009",
    "naval-treaty-0007",
]
VERDICTS = ("ok", "fixed", "drop", "unsure")
CSV_FIELDS = ["item_id", "set", "assignee", "reviewer", "date", "verdict", "fix", "time_min"]
CONTEXT_CHARS = 700


def rank(item_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{item_id}".encode()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def confidence(item: dict) -> str:
    m = re.search(r"confidence=(\w+)", item.get("notes", ""))
    return m.group(1) if m else "unknown"


def select(golden: list[dict], contra: list[dict], split: dict) -> tuple[list[str], list[str]]:
    """Golden: the named ids, then test-split ids (seeded order) up to 20, at least 6 of them
    beyond the named ones. Contradictions: the named ids, then the least confident others."""
    have = {g["id"] for g in golden}
    test = [i for i in split["content"]["golden"]["test"] if i in have and i not in NAMED_GOLDEN]
    extra = sorted(test, key=rank)[: max(N_TEST_EXTRA, N_GOLDEN - len(NAMED_GOLDEN))]
    g_ids = sorted(NAMED_GOLDEN + extra)
    order = {"low": 0, "medium": 1, "high": 2, "unknown": 3}
    rest = [c for c in contra if c["id"] not in NAMED_CONTRA]
    rest.sort(key=lambda c: (order.get(confidence(c), 3), rank(c["id"])))
    c_ids = sorted(NAMED_CONTRA + [c["id"] for c in rest[: N_CONTRA - len(NAMED_CONTRA)]])
    return g_ids, c_ids


def find(text: str, quote: str) -> list[re.Match[str]]:
    """Occurrences of a quote in a text, whitespace-insensitive (as validate_golden.py)."""
    words = quote.split()
    if not words:
        return []
    return list(re.finditer(r"\s+".join(map(re.escape, words)), text))


def passage(text: str, m: re.Match[str]) -> str:
    """The quote's paragraph(s), at most CONTEXT_CHARS on each side, the quote in bold."""
    start = text.rfind("\n\n", 0, m.start())
    start = max(start + 2 if start >= 0 else 0, m.start() - CONTEXT_CHARS)
    end = text.find("\n\n", m.end())
    end = min(end if end >= 0 else len(text), m.end() + CONTEXT_CHARS)
    flat = lambda s: re.sub(r"\s+", " ", s)  # noqa: E731
    head = "..." if start > 0 and text[start - 1] not in "\n" else ""
    tail = "..." if end < len(text) and text[end] not in "\n" else ""
    return f"{head}{flat(text[start : m.start()])}**{flat(m.group(0))}**{flat(text[m.end() : end])}{tail}"


def quote_block(corpus: dict[str, str], story: str, quote: str) -> tuple[str, str]:
    """(pre-check line, markdown passage) for one quote."""
    if story not in corpus:
        return f"FAIL: no story file `{story}`", ""
    hits = find(corpus[story], quote)
    if not hits:
        return f"FAIL: quote NOT found verbatim in `{story}.txt`", ""
    note = (
        "verbatim, 1 place"
        if len(hits) == 1
        else f"verbatim, {len(hits)} places (the first is shown)"
    )
    return note, "> " + passage(corpus[story], hits[0])


def golden_sheet(items: list[dict], corpus: dict[str, str], split_of: dict[str, str]) -> list[str]:
    out = []
    for g in items:
        out += [
            f"## {g['id']} · {g['category']} · {split_of.get(g['id'], '?')} split · {g['lang']}",
            "",
            f"**Question:** {g['question']}",
            "",
            f"**Expected answer:** {g['expected_answer']}",
            "",
            f"**Expected behaviour:** `{g['expected_behavior']}` · answerable: `{g['answerable']}`",
            "",
            f"**Author's note:** {g['notes']}",
            "",
        ]
        if not g["gold_quotes"]:
            out += [
                "**Gold quotes:** none (not answerable from the corpus). Check that the corpus really has no answer.",
                "",
            ]
        for k, q in enumerate(g["gold_quotes"], 1):
            check, text = quote_block(corpus, q["story"], q["quote"])
            out += [f"**Gold quote {k}** (`{q['story']}`) · pre-check: {check}", "", text, ""]
        out += [
            "Check: (1) the question is well posed and answerable as marked; (2) each quote supports the",
            "expected answer; (3) the answer is complete and not stronger than the text; (4) behaviour is right.",
            "",
            "---",
            "",
        ]
    return out


def contra_sheet(items: list[dict], corpus: dict[str, str], split_of: dict[str, str]) -> list[str]:
    out = []
    for c in items:
        out += [
            f"## {c['id']} · {c['kind']} · {split_of.get(c['id'], '?')} split · `{c['story']}`",
            "",
            f"**Question:** {c['question']}",
            "",
            f"**Expected finding:** `{c['expected_finding']}` · evidence `{c['evidence_strength']}` · needs time normalisation `{c['needs_time_normalisation']}`",
            "",
            f"**Expected description:** {c['expected_description']}",
            "",
            f"**Author's note:** {c['notes']}",
            "",
        ]
        for k, cl in enumerate(c["involved_claims"], 1):
            check, text = quote_block(corpus, c["story"], cl["quote"])
            out += [f"**Claim {k}:** {cl['who']}: {cl['what']} · pre-check: {check}", "", text, ""]
        out += [
            "Check: (1) each quote says what its line says, and the speaker is right; (2) the finding",
            "(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.",
            "",
            "---",
            "",
        ]
    return out


def extraction_rows(chunk: dict) -> list[tuple[str, dict]]:
    g = chunk["gold"]
    rows = [(f"x:{chunk['chunk_id']}:claim:{i}", c) for i, c in enumerate(g.get("claims", []), 1)]
    rows += [
        (f"x:{chunk['chunk_id']}:relation:{i}", r) for i, r in enumerate(g.get("relations", []), 1)
    ]
    return rows


def extraction_sheet(chunks: list[dict]) -> list[str]:
    out = []
    for ch in chunks:
        out += [f"## {ch['chunk_id']} (`{ch['story']}`)", "", "Chunk text:", ""]
        out += ["> " + para.replace("\n", " ") for para in ch["text"].split("\n\n")] + [""]
        for item_id, it in extraction_rows(ch):
            n = len(find(ch["text"], it["quote"]))
            check = "verbatim in the chunk" if n else "FAIL: quote not in the chunk"
            if ":claim:" in item_id:
                line = f"speaker **{it['speaker']}** says, about **{it['about']}**: {it['content']}"
            else:
                line = f"**{it['subject']}** · {it['predicate']} · **{it['object']}**"
            out += [f"- `{item_id}` {line}  ", f'  quote: "{it["quote"]}" · pre-check: {check}']
        out += [
            "",
            "Check each claim: speaker, content and 'about' are right and supported; each relation: subject,",
            "predicate and object are right. Note missing claims or relations in `fix` of the chunk's first row.",
            "",
            "---",
            "",
        ]
    return out


def build(out: Path, date: str) -> dict:
    golden, contra = load_jsonl(GOLDEN), load_jsonl(CONTRA)
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    split_of = {
        i: part
        for kind in ("golden", "contradictions")
        for part in ("dev", "test")
        for i in split["content"][kind][part]
    }
    corpus = {p.stem: p.read_text(encoding="utf-8") for p in sorted(CLEAN.glob("*.txt"))}
    g_ids, c_ids = select(golden, contra, split)
    g_items = [g for g in golden if g["id"] in g_ids]
    c_items = [c for c in contra if c["id"] in c_ids]
    chunks = [
        json.loads((EXTRACTION / f"{cid}.json").read_text(encoding="utf-8")) for cid in CHUNKS
    ]
    out.mkdir(parents=True, exist_ok=True)
    head = lambda title: [  # noqa: E731
        f"# {title}",
        "",
        f"Review kit of {date} for issue #9, built by `scripts/eval/review_kit.py` (seed `{SEED}`).",
        "Passages are from `data/clean/`; the quote is in bold. **The pre-check is a script, not a review.**",
        "Write your verdict in `verdicts.csv` (see README.md).",
        "",
    ]
    (out / "golden.md").write_text(
        "\n".join(head("Golden questions: review sheet") + golden_sheet(g_items, corpus, split_of)),
        encoding="utf-8",
    )
    (out / "contradictions.md").write_text(
        "\n".join(
            head("Contradiction cases: review sheet") + contra_sheet(c_items, corpus, split_of)
        ),
        encoding="utf-8",
    )
    (out / "extraction.md").write_text(
        "\n".join(head("Extraction gold: review sheet") + extraction_sheet(chunks)),
        encoding="utf-8",
    )
    rows = [(g, "golden") for g in g_ids] + [(c, "contradictions") for c in c_ids]
    rows += [(item_id, "extraction") for ch in chunks for item_id, _ in extraction_rows(ch)]
    # two reviewers, alternate items (whole chunks stay with one person)
    with (out / "verdicts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for n, (item_id, kind) in enumerate(rows):
            if kind == "extraction":
                who = "A" if CHUNKS.index(item_id.split(":")[1]) % 2 == 0 else "B"
            else:
                who = "A" if n % 2 == 0 else "B"
            w.writerow({"item_id": item_id, "set": kind, "assignee": who})
    fails = sum(
        t.count("pre-check: FAIL")
        for t in (
            (out / n).read_text(encoding="utf-8")
            for n in ("golden.md", "contradictions.md", "extraction.md")
        )
    )
    return {
        "golden": g_ids,
        "contradictions": c_ids,
        "chunks": CHUNKS,
        "extraction_rows": sum(len(extraction_rows(c)) for c in chunks),
        "precheck_failures": fails,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--out", help="default: eval/review/<date>")
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else ROOT / "eval" / "review" / args.date
    summary = build(out, args.date)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
