"""Loader of the CURATED presence facts for the demo cases (docs/symbolic-layer.md 11.4).

    python -m detective_board.extract.curated --graph-db data/graph/graph.sqlite \\
        [--file data/curated/presence_demo.jsonl] [--chunks data/chunks.jsonl] \\
        [--clean-dir data/clean]

Reads human-checked facts (`CuratedFact`, one JSON object per line), checks that every quote is a
verbatim span of the story's clean text and that each slot is either in the quote or declared
`inferred`, finds the chunk that holds the quote and ingests the fact with
`GraphStore.ingest_curated`. Run it after the graph build and after `extract.normalise`; it is
idempotent and its nodes survive generic and presence re-ingests. The automatic pipeline is
evaluated separately and is not touched.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from detective_board.extract.curated_schema import CuratedFact
from detective_board.graph.anchors import ChunkRef
from detective_board.graph.normalize import fold_text
from detective_board.graph.store import GraphStore

DEFAULT_FILE = "data/curated/presence_demo.jsonl"
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def load_file(path: str | Path) -> list[CuratedFact]:
    """Parse a JSONL file of curated facts. Blank lines and `#` lines are skipped; duplicate ids and
    invalid records raise ValueError with the line number."""
    facts: list[CuratedFact] = []
    seen: set[str] = set()
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            fact = CuratedFact.model_validate(json.loads(line))
        except ValueError as exc:
            raise ValueError(f"{path}:{n}: {exc}") from exc
        if fact.id in seen:
            raise ValueError(f"{path}:{n}: duplicate id {fact.id!r}")
        seen.add(fact.id)
        facts.append(fact)
    return facts


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Text with curly quotes straightened and whitespace runs collapsed to one space, plus the
    index of each kept character in the original text."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text.translate(_QUOTES)):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx.append(i)
            prev_space = True
        else:
            out.append(ch)
            idx.append(i)
            prev_space = False
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normalise_quote(text: str) -> str:
    return _norm_map(text)[0]


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """(start, end) of `quote` in `text` after whitespace and quotation-mark normalisation, in the
    original text's offsets; None when the quote is not a verbatim span. The first match wins."""
    nt, idx = _norm_map(text)
    nq = normalise_quote(quote)
    if not nq:
        return None
    s = nt.find(nq)
    if s < 0:
        return None
    return idx[s], idx[s + len(nq) - 1] + 1


def problems(fact: CuratedFact, clean_text: str) -> list[str]:
    """Why a fact cannot be loaded as written; empty when it is sound. Checks: the quote is a
    verbatim span of the story; time_text and day_text are in the quote; person, place and speaker
    are in the quote unless the slot is declared `inferred` (the note then has to say why)."""
    out: list[str] = []
    if locate_quote(clean_text, fact.quote) is None:
        return [f"{fact.id}: quote is not a verbatim span of the story text"]
    q = normalise_quote(fact.quote).casefold()
    for name, val in (("time_text", fact.time_text), ("day_text", fact.day_text)):
        if val and normalise_quote(val).casefold() not in q:
            out.append(f"{fact.id}: {name} {val!r} is not in the quote")
    person_in = fold_text(fact.person.split()[-1]) in fold_text(fact.quote).split()
    if not person_in and "person" not in fact.inferred:
        out.append(f"{fact.id}: person {fact.person!r} is not in the quote; declare it inferred")
    if person_in and "person" in fact.inferred:
        out.append(f"{fact.id}: person {fact.person!r} is in the quote but declared inferred")
    place_in = normalise_quote(fact.place).casefold() in q
    if not place_in and "place" not in fact.inferred:
        out.append(f"{fact.id}: place {fact.place!r} is not in the quote; declare it inferred")
    if place_in and "place" in fact.inferred:
        out.append(f"{fact.id}: place {fact.place!r} is in the quote but declared inferred")
    if fact.time_text is None and fact.time_ref is None and "time" in fact.inferred:
        out.append(f"{fact.id}: time declared inferred but there is no time_text or time_ref")
    if fact.time_ref_text:
        if normalise_quote(fact.time_ref_text).casefold() not in q:
            out.append(f"{fact.id}: time_ref_text {fact.time_ref_text!r} is not in the quote")
        if "time" in fact.inferred:
            out.append(f"{fact.id}: time_ref_text is in the quote but time is declared inferred")
    elif fact.time_ref is not None and "time" not in fact.inferred:
        out.append(f"{fact.id}: time_ref without time_ref_text: declare time inferred")
    if fact.inferred and not re.search(r"infer|resolv|context|imply|implied", fact.note, re.I):
        out.append(f"{fact.id}: inferred slots need a note that says why")
    return out


@dataclass
class LoadReport:
    loaded: int = 0
    unchanged: int = 0
    by_fact: dict[str, str] = field(default_factory=dict)  # fact id -> chunk id / status

    def line(self) -> str:
        return f"curated facts: {self.loaded} loaded, {self.unchanged} unchanged"


def _chunk_for(chunks: Iterable[ChunkRef], quote: str) -> tuple[ChunkRef, str] | None:
    """First chunk (by chunk id) that holds the whole quote; the quote is returned with the
    chunk's own characters so the anchor is exact."""
    for c in sorted(chunks, key=lambda c: c.chunk_id):
        span = locate_quote(c.text, quote)
        if span is not None:
            return c, c.text[span[0] : span[1]]
    return None


def load_chunks(path: str | Path, stories: set[str], clean_dir: str | Path) -> list[ChunkRef]:
    out: list[ChunkRef] = []
    clean: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec["story"] not in stories:
            continue
        story = rec["story"]
        if story not in clean:
            clean[story] = (Path(clean_dir) / f"{story}.txt").read_text(encoding="utf-8")
        out.append(ChunkRef.from_record(rec, clean[story]))
    return out


def ingest_facts(
    store: GraphStore,
    facts: Sequence[CuratedFact],
    chunks: Sequence[ChunkRef],
    clean_texts: dict[str, str],
) -> LoadReport:
    """Validate and ingest. Raises ValueError listing every problem before anything is written."""
    errors: list[str] = []
    placed: list[tuple[ChunkRef, CuratedFact]] = []
    for f in facts:
        clean = clean_texts.get(f.story)
        if clean is None:
            errors.append(f"{f.id}: no clean text for story {f.story!r}")
            continue
        errs = problems(f, clean)
        errors += errs
        if errs:
            continue
        hit = _chunk_for([c for c in chunks if c.story == f.story], f.quote)
        if hit is None:
            errors.append(f"{f.id}: no single chunk holds the whole quote")
            continue
        chunk, exact = hit
        placed.append((chunk, f.model_copy(update={"quote": exact})))
    if errors:
        raise ValueError("curated facts not loaded:\n" + "\n".join(errors))
    rep = LoadReport()
    for chunk, f in placed:
        r = store.ingest_curated(chunk, [f])[0]
        rep.by_fact[f.id] = chunk.chunk_id
        if r.status == "unchanged":
            rep.unchanged += 1
        else:
            rep.loaded += 1
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="curated", description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--graph-db", required=True, help="graph SQLite file (data/graph/graph.sqlite)")
    ap.add_argument("--file", default=DEFAULT_FILE, help=f"curated facts, JSONL ({DEFAULT_FILE})")
    ap.add_argument("--chunks", default="data/chunks.jsonl")
    ap.add_argument("--clean-dir", default="data/clean")
    ns = ap.parse_args(argv)
    facts = load_file(ns.file)
    stories = {f.story for f in facts}
    clean = {s: (Path(ns.clean_dir) / f"{s}.txt").read_text(encoding="utf-8") for s in stories}
    chunks = load_chunks(ns.chunks, stories, ns.clean_dir)
    store = GraphStore(ns.graph_db)
    try:
        rep = ingest_facts(store, facts, chunks, clean)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        store.close()
    print(rep.line())
    for fid, cid in rep.by_fact.items():
        print(f"  {fid} -> {cid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
