#!/usr/bin/env python3
"""Validate eval/pre_reveal/cases.jsonl (stdlib only).

Hard checks (exit 1): JSON per line, required fields and types, unique ids, known story, cut offset
inside the text, every reveal quote is a VERBATIM substring of data/clean/<story>.txt, the cut lies
before the START of every reveal quote, the question does not already contain the answer keywords,
and the text BEFORE the cut cannot answer the question by keywords:
  * no sentence before the cut holds all keywords of any keyword set (truth_keywords and each
    truth_keywords_alt set);
  * no chunk of data/chunks.jsonl that ends at or before the cut holds all keywords of a set
    (a cited chunk would score as correct without any reveal);
  * no 'X is/was the murderer|culprit|killer|guilty man|thief' sentence before the cut for a keyword X.
Matching is case-insensitive and starts at a word boundary (a keyword may be a phrase).
Also: culprit_names (the primary metric's accepted names/aliases) is a non-empty list of non-empty
phrase lists, no alias set is in the question, cleared_names is a list of names that matches no
culprit alias. The culprit aliases are NOT required to be absent before the cut (Turner and
Cunningham are characters from the start); `--exposure` prints how many pre-cut chunks hold each.

What this CANNOT check (say so in every report): that the cut precedes every paraphrase of the
solution (a hint worded without the keywords passes); that Holmes does not name the culprit by a
description ('the Australian', 'the horse') in a sentence without the keywords; that the cut is at
the right place in the author's intent (a human has to read the rationale); that keywords do not
occur across SEVERAL pre-cut chunks of one answer; that the bare model has not memorised the story;
that the quotes are the only reveal passages (they are examples, the cut is what counts).

Usage: python3 scripts/eval/validate_pre_reveal.py [--exposure] [cases.jsonl] [clean_dir] [chunks.jsonl]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {
    "id": str,
    "story": str,
    "cut_char": int,
    "question": str,
    "truth": str,
    "truth_keywords": list,
    "reveal_quotes": list,
    "rationale": str,
    "culprit_names": list,
}
ROLE = r"(?:the\s+)?(?:murderer|culprit|killer|guilty(?:\s+man)?|thief|criminal|villain)"
SENT_END = re.compile(r"(?<=[.!?])[\"'’”)]*\s+|\n+")


def kw_re(kw: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z])" + re.escape(kw), re.IGNORECASE)


def has_all(text: str, kws: list[str]) -> bool:
    return all(kw_re(k).search(text) for k in kws)


def keyword_sets(case: dict) -> list[list[str]]:
    return [case["truth_keywords"], *case.get("truth_keywords_alt", [])]


def sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) spans of sentences (best effort: sentence-final punctuation or a newline)."""
    spans, pos = [], 0
    for m in SENT_END.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return spans


def check_case(case: dict, text: str, chunks: list[dict], seen: set[str], where: str) -> list[str]:
    errs: list[str] = []
    for key, typ in FIELDS.items():
        if key not in case:
            errs.append(f"{where}: missing field {key}")
        elif not isinstance(case[key], typ) or isinstance(case[key], bool):
            errs.append(f"{where}: field {key} must be {typ.__name__}")
    if errs:
        return errs
    if case["id"] in seen:
        errs.append(f"{where}: duplicate id {case['id']}")
    seen.add(case["id"])
    cut = case["cut_char"]
    if not 0 < cut < len(text):
        return [*errs, f"{where}: cut_char {cut} outside the text (len {len(text)})"]
    if not case["reveal_quotes"]:
        errs.append(f"{where}: no reveal_quotes")
    kwsets = keyword_sets(case)
    if not case["truth_keywords"] or not all(
        isinstance(s, list) and s and all(isinstance(k, str) and k for k in s) for s in kwsets
    ):
        return [*errs, f"{where}: truth_keywords / truth_keywords_alt must be lists of strings"]
    names = case["culprit_names"]
    if not names or not all(
        isinstance(s, list) and s and all(isinstance(k, str) and k for k in s) for s in names
    ):
        errs.append(f"{where}: culprit_names must be a non-empty list of non-empty string lists")
        names = []
    for s in names:
        if has_all(case["question"], s):
            errs.append(f"{where}: the question already contains the culprit alias {s}")
    cleared = case.get("cleared_names", [])
    if not isinstance(cleared, list) or not all(isinstance(k, str) and k for k in cleared):
        errs.append(f"{where}: cleared_names must be a list of non-empty strings")
    else:
        for k in cleared:
            if any(has_all(k, s) for s in names):
                errs.append(f"{where}: cleared name {k!r} matches a culprit alias")
    for q in case["reveal_quotes"]:
        i = text.find(q)
        if i < 0:
            errs.append(f"{where}: quote not verbatim in the clean text: {q[:60]!r}")
        elif i < cut:
            errs.append(f"{where}: quote starts at {i}, before the cut {cut}: {q[:60]!r}")
    if text[cut - 1] != "\n" and text[cut - 2 : cut] != "\n\n":
        errs.append(f"{where}: cut_char {cut} is not at a paragraph start (must follow a newline)")
    for kws in kwsets:
        if has_all(case["question"], kws):
            errs.append(f"{where}: the question already contains the keywords {kws}")
    before = text[:cut]
    for kws in kwsets:
        for s, e in sentences(before):
            if has_all(before[s:e], kws):
                errs.append(
                    f"{where}: pre-cut sentence at {s} holds all of {kws}: {before[s:e][:80]!r}"
                )
                break
        for ch in chunks:
            if ch["story"] == case["story"] and ch["char_end"] <= cut and has_all(ch["text"], kws):
                errs.append(f"{where}: pre-cut chunk {ch['chunk_id']} holds all of {kws}")
                break
    for kws in kwsets:
        for k in kws:
            pat = re.compile(
                r"(?<![A-Za-z])" + re.escape(k) + r"[^.!?]{0,40}\b(?:is|was|are|were)\s+" + ROLE,
                re.IGNORECASE,
            )
            m = pat.search(before)
            if m:
                errs.append(
                    f"{where}: pre-cut 'X is the culprit' form at {m.start()}: {m.group(0)!r}"
                )
    return errs


def load(path: Path) -> list[tuple[int, dict | str]]:
    rows: list[tuple[int, dict | str]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append((n, json.loads(line)))
        except json.JSONDecodeError as exc:
            rows.append((n, f"invalid JSON: {exc}"))
    return rows


def validate(cases_path: Path, clean_dir: Path, chunks_path: Path) -> list[str]:
    errs: list[str] = []
    rows = load(cases_path)
    chunks = [json.loads(x) for x in chunks_path.read_text(encoding="utf-8").splitlines() if x]
    texts: dict[str, str] = {}
    seen: set[str] = set()
    for n, case in rows:
        where = f"line {n}"
        if isinstance(case, str):
            errs.append(f"{where}: {case}")
            continue
        story = case.get("story")
        if not isinstance(story, str) or not (clean_dir / f"{story}.txt").exists():
            errs.append(f"{where}: unknown story {story!r}")
            continue
        if story not in texts:
            texts[story] = (clean_dir / f"{story}.txt").read_text(encoding="utf-8")
        errs += check_case(case, texts[story], chunks, seen, where)
    if len({c["story"] for _, c in rows if isinstance(c, dict) and "story" in c}) < 8:
        errs.append("fewer than 8 stories")
    cuts = {(c["story"], c["cut_char"]) for _, c in rows if isinstance(c, dict) and "cut_char" in c}
    if len(cuts) != len({s for s, _ in cuts}):
        errs.append("one story has two different cut_char values")
    return errs


def exposure(cases_path: Path, chunks_path: Path) -> list[str]:
    """Info lines: per case and culprit alias set, the pre-cut chunks that hold it."""
    chunks = [json.loads(x) for x in chunks_path.read_text(encoding="utf-8").splitlines() if x]
    out = []
    for _, case in load(cases_path):
        if not isinstance(case, dict):
            continue
        pre = [
            c["text"]
            for c in chunks
            if c["story"] == case["story"] and c["char_end"] <= case["cut_char"]
        ]
        counts = {
            "+".join(s): sum(has_all(t, s) for t in pre) for s in case.get("culprit_names", [])
        }
        out.append(f"{case['id']}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return out


def main(argv: list[str]) -> int:
    show = "--exposure" in argv
    argv = [a for a in argv if a != "--exposure"]
    cases = Path(argv[1]) if len(argv) > 1 else ROOT / "eval" / "pre_reveal" / "cases.jsonl"
    clean = Path(argv[2]) if len(argv) > 2 else ROOT / "data" / "clean"
    chunks = Path(argv[3]) if len(argv) > 3 else ROOT / "data" / "chunks.jsonl"
    errs = validate(cases, clean, chunks)
    if show:
        for line in exposure(cases, chunks):
            print("INFO pre-cut chunks holding a culprit alias:", line)
    for e in errs:
        print("ERROR", e)
    if not errs:
        print(f"OK: {cases} valid")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
