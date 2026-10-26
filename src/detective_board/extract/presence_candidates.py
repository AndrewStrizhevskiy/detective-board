"""Candidate lists for the presence pass `presence-2` (docs/symbolic-layer.md 11.3).

A small model cannot resolve "he" by free generation but can pick from a short list. For each chunk
we build the persons and places the generic extraction already found there, from (in order of
preference, `--candidates graph|cache|text` picks where to start):

 - graph: `g_mention` rows of the chunk joined to named person/place `g_node` rows (mentions made
   by the presence pass itself are left out, so a rerun sees the same lists);
 - cache: the generic extraction cache entry of the chunk (entity items of type person/place);
 - text: a cheap deterministic capitalised-name detector over the chunk text.

Each list is capped (`MAX_CANDIDATES`, most mentioned first, ties by name) to keep the prompt and
the `enum` of the JSON schema short. Pure functions; no LLM.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from detective_board.extract.parse import parse_output
from detective_board.graph.normalize import fold_text

UNKNOWN = "UNKNOWN"
MAX_CANDIDATES = 30
TOP_STORY_PEOPLE = 8
TOP_STORY_PLACES = 5
MODES = ("graph", "cache", "text")


@dataclass(frozen=True)
class Candidates:
    people: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # prompt display only
    source: str = "text"
    carry: int = 0  # chunks of carry-over used (part of the hash)

    def sha(self) -> str:
        """Hash of the carry setting, both lists (in offered order) and the aliases."""
        blob = json.dumps(
            [
                self.carry,
                list(self.people),
                list(self.places),
                {k: list(v) for k, v in sorted(self.aliases.items())},
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def render(self, names: Iterable[str]) -> str:
        parts = []
        for n in names:
            al = self.aliases.get(n)
            parts.append(f"{n} (also: {', '.join(al)})" if al else n)
        return "; ".join(parts) if parts else "(none found)"

    def people_text(self) -> str:
        return self.render(self.people)

    def places_text(self) -> str:
        return self.render(self.places)


def rank(
    counts: Mapping[str, int], cap: int = MAX_CANDIDATES, exclude: frozenset[str] = frozenset()
) -> tuple[str, ...]:
    """Names by mention count (descending), ties by name; case-insensitive duplicates merged;
    the literal UNKNOWN never a candidate; at most `cap`."""
    merged: dict[str, tuple[str, int]] = {}
    for name, n in counts.items():
        name = " ".join(name.split())
        k = name.casefold()
        if not name or k == UNKNOWN.casefold() or k in exclude:
            continue
        old = merged.get(k)
        merged[k] = (old[0] if old and old[1] >= n else name, (old[1] if old else 0) + n)
    ordered = sorted(merged.values(), key=lambda t: (-t[1], t[0]))
    return tuple(n for n, _ in ordered[:cap])


def _aliases(
    names: Iterable[str], alias_map: Mapping[str, Iterable[str]]
) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for n in names:
        al = tuple(dict.fromkeys(a for a in alias_map.get(n, ()) if a and a != n))[:3]
        if al:
            out[n] = al
    return out


def _build(
    people: Mapping[str, int],
    places: Mapping[str, int],
    alias_map: Mapping[str, Iterable[str]],
    source: str,
    cap: int,
) -> Candidates | None:
    pe, pl = rank(people, cap), rank(places, cap)
    if not pe and not pl:
        return None
    return Candidates(pe, pl, _aliases([*pe, *pl], alias_map), source)


# --------------------------------------------------------------------------- graph


def _presence_mentions(store: Any, like: str) -> set[int]:
    """Ids of the mentions made by the presence pass (g_meta `presence:<chunk>`) matching `like`."""
    out: set[int] = set()
    for r in store.conn.execute("SELECT value FROM g_meta WHERE key LIKE ?", (f"presence:{like}",)):
        out.update(json.loads(r["value"]).get("mentions", []))
    return out


def _tally(store: Any, where: str, args: tuple, own: set[int]):
    people: Counter[str] = Counter()
    places: Counter[str] = Counter()
    alias_map: dict[str, list[str]] = {}
    rows = store.conn.execute(
        "SELECT m.id AS mid, n.kind AS kind, n.name AS name, n.props_json AS props"
        " FROM g_mention m JOIN g_node n ON n.id=m.node_id"
        f" WHERE {where} AND n.kind IN ('person','place') AND n.unnamed=0"
        " AND n.name IS NOT NULL AND m.role IN ('name','alias') ORDER BY m.id",
        args,
    )
    for r in rows:
        if r["mid"] in own:
            continue
        (people if r["kind"] == "person" else places)[r["name"]] += 1
        alias_map.setdefault(r["name"], list(json.loads(r["props"]).get("aliases", [])))
    return people, places, alias_map


def split_chunk_id(chunk_id: str) -> tuple[str, int, int] | None:
    """('story', index, zero-pad width) of an id like 'story-0006'."""
    head, _, tail = chunk_id.rpartition("-")
    return (head, int(tail), len(tail)) if head and tail.isdigit() else None


def candidates_from_graph(
    store: Any,
    chunk_id: str,
    cap: int = MAX_CANDIDATES,
    carry: int = 0,
    top_people: int = TOP_STORY_PEOPLE,
    top_places: int = TOP_STORY_PLACES,
) -> Candidates | None:
    """Named persons/places for `chunk_id` in a GraphStore, or None if there are none at all.

    Order: the chunk's own names (never cut by the cap), then those of the previous `carry` chunks
    of the same story (nearest first; chunk index from the id), then the story's `top_people` /
    `top_places` most mentioned; de-duplicated, at most `cap` in total."""
    sid = split_chunk_id(chunk_id)
    own = _presence_mentions(store, f"{chunk_id}")
    pe, pl, al = _tally(store, "m.chunk_id=?", (chunk_id,), own)
    people = list(rank(pe, cap))
    places = list(rank(pl, cap))
    aliases = dict(al)

    def extend(dest: list[str], names: Iterable[str]) -> None:
        seen = {x.casefold() for x in dest}
        for n in names:
            if len(dest) < cap and n.casefold() not in seen:
                dest.append(n)
                seen.add(n.casefold())

    if sid and carry > 0:
        story, idx, width = sid
        for k in range(1, carry + 1):
            if idx - k < 0:
                break
            cid = f"{story}-{idx - k:0{width}d}"
            a, b, al2 = _tally(store, "m.chunk_id=?", (cid,), _presence_mentions(store, cid))
            aliases = {**al2, **aliases}
            extend(people, rank(a, cap))
            extend(places, rank(b, cap))
    if not people and not places:
        return None
    if sid and (top_people or top_places):
        story = sid[0]
        a, b, al3 = _tally(store, "n.story=?", (story,), _presence_mentions(store, f"{story}-%"))
        aliases = {**al3, **aliases}
        extend(people, rank(a, top_people))
        extend(places, rank(b, top_places))
    return Candidates(
        tuple(people), tuple(places), _aliases([*people, *places], aliases), "graph", carry
    )


# --------------------------------------------------------------------------- generic cache


def candidates_from_extraction(
    raw_text: str, chunk_text: str, cap: int = MAX_CANDIDATES
) -> Candidates | None:
    """Entities (type person/place) of one generic-extraction output (a cache entry's text)."""
    data = parse_output(raw_text).data
    if not data or not isinstance(data.get("entities"), list):
        return None
    low = fold_text(chunk_text)
    people: Counter[str] = Counter()
    places: Counter[str] = Counter()
    alias_map: dict[str, list[str]] = {}
    for e in data["entities"]:
        if not isinstance(e, dict) or e.get("unnamed"):
            continue
        name, kind = e.get("name"), e.get("type")
        if not isinstance(name, str) or not name.strip() or kind not in ("person", "place"):
            continue
        al = [a for a in e.get("aliases", []) if isinstance(a, str)]
        n = sum(low.count(fold_text(x)) for x in [name, *al] if fold_text(x))
        (people if kind == "person" else places)[name.strip()] += max(n, 1)
        alias_map.setdefault(name.strip(), al)
    return _build(people, places, alias_map, "cache", cap)


# --------------------------------------------------------------------------- text detector

_CAPWORD = r"[A-Z][a-zA-Z’'\-]*"
_TITLE = (
    r"(?:Mr|Mrs|Dr|St|Messrs|Mister|Miss|Captain|Inspector|Colonel|Sir|Lord|Lady|Professor|Major"
    r"|Sergeant)"
)
_RUN = re.compile(rf"(?:{_TITLE}\.?\s+)?{_CAPWORD}(?:\s+(?:de|of|von|van)?\s*{_CAPWORD})*")
_STOP = frozenset(
    "the a an i he she it we you they his her their our my your its this that these those there "
    "here and but or if when while as so then now yes no oh well what who which how why where "
    "after before since at in on to of for with from by not all some one two three monday tuesday "
    "wednesday thursday friday saturday sunday january february march april may june july august "
    "september october november december god sir madam".split()
)
_LOCATIVE = frozenset(
    "at in to into near from upon on by towards toward inside outside beside through across "
    "reached entered".split()
)
_PLACE_WORDS = frozenset(
    "lodge manor common hall street road station pool lane park abbey bridge house farm inn arms "
    "court square gardens row hotel church castle wood heath town city village island".split()
)


def candidates_from_text(text: str, cap: int = MAX_CANDIDATES) -> Candidates | None:
    """Capitalised runs of the chunk: places after a locative word or ending in a place noun,
    else persons. A single word that only ever opens sentences is skipped."""
    people: Counter[str] = Counter()
    places: Counter[str] = Counter()
    for m in _RUN.finditer(text):
        words = m.group(0).split()
        while words and words[0].rstrip(".").casefold() in _STOP:
            words.pop(0)
        while words and words[-1].casefold() in _STOP:
            words.pop()
        if not words:
            continue
        name = " ".join(words)
        before = text[: m.start()].rstrip()
        sentence_start = not before or before[-1] in '.!?"“‘”’'
        if len(words) == 1 and sentence_start and words[0].casefold() in _STOP | _PLACE_WORDS:
            continue
        prevs = [w.casefold().strip("\"'“‘,.;:") for w in before.split()[-2:]]
        after_loc = bool(prevs) and (
            prevs[-1] in _LOCATIVE
            or (prevs[-1] in ("the", "a", "an") and len(prevs) == 2 and prevs[0] in _LOCATIVE)
        )
        is_place = words[-1].casefold() in _PLACE_WORDS or after_loc
        (places if is_place else people)[name] += 1
    # a lone surname/first word that ends a longer known person name counts for that name
    for short in [p for p in people if " " not in p]:
        longer = [p for p in people if p != short and p.split()[-1] == short]
        if len(longer) == 1:
            people[longer[0]] += people.pop(short)
    return _build(people, places, {}, "text", cap)


# --------------------------------------------------------------------------- selection


@dataclass
class CandidateSource:
    """Candidates for one chunk by mode with fallbacks (graph -> cache -> text; cache -> text)."""

    mode: str = "graph"
    store: Any = None
    generic_lookup: Callable[[str], dict | None] | None = None  # chunk text -> raw cache entry
    cap: int = MAX_CANDIDATES
    carry: int = 0

    def for_chunk(self, chunk_id: str, text: str) -> Candidates:
        if self.mode == "graph" and self.store is not None:
            c = candidates_from_graph(self.store, chunk_id, self.cap, self.carry)
            if c is not None:
                return c
        if self.mode in ("graph", "cache") and self.generic_lookup is not None:
            rec = self.generic_lookup(text)
            c = candidates_from_extraction(rec["text"], text, self.cap) if rec else None
            if c is not None:
                return c
        return candidates_from_text(text, self.cap) or Candidates(source="text")
