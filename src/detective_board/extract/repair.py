"""Deterministic grounding/repair of a parsed extraction (docs/symbolic-layer.md 11.2).

Measured on qwen3:4b / extract-2.1 the model fills structured fields by habit: `participants`
empty, `time_text`/`place` copied from the start of the chunk, `polarity` 'deny' for 98% of claims,
`about_person` always set. This module checks every such field against the item's own quote (and
the chunk text) and fixes what it can. No LLM, clock or randomness: the same input gives the same
output, and a second pass changes nothing. The raw cache is untouched; the repair runs after
parsing, so cache hits are repaired too and `REPAIR_VERSION` is not part of the cache key.

Rules (R = repair rule, audit fields in `schema_v2.REPAIR_FIELDS`):
 R1 participants: person entities (name or alias, graph.normalize rules; unique surnames too)
    mentioned in the event's quote or description are added; model-provided names that are
    grounded stay, ungrounded ones are dropped (kept in `participants_model`).
 R2 polarity: 'deny' only on an explicit negation cue in the claim's own quote, else 'affirm'.
 R3 in_speech: true iff the event's quote lies inside a quotation span of the chunk text.
 R4 time_text/place of an event stay only when the expression appears in the event's quote or
    description; otherwise they move to `time_text_inherited` / `place_inherited`. A time
    without any temporal cue (or equal to the whole quote) and a place that is neither a place
    entity nor a capitalised name are dropped (`TIME_NOT_TEMPORAL`, `PLACE_NOT_A_PLACE`).
 R5 claim about_person/about_place/about_time_text stay only when they appear in the claim's quote
    or content (about_person also when it is the speaker of a first-person quote); else null.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from detective_board.extract import schema_v2
from detective_board.extract.ground import normalise as ground_normalise
from detective_board.graph.normalize import (
    DETERMINERS,
    PRONOUNS,
    TITLES,
    fold_text,
    normalize_name,
)

REPAIR_VERSION = "1"

Items = dict[str, list[dict[str, Any]]]

_NEGATION = re.compile(
    r"\b(?:not|never|no one|nobody|nothing|none|neither|nor|cannot|without|"
    r"den(?:y|ies|ied|ying)|refus(?:e|es|ed|ing|al))\b|n't\b"
)
_FIRST_PERSON = re.compile(r"\b(?:I|me|my|mine|myself|I'm|I've|I'd|I'll|we|We|our|us)\b")
_NUMBER_WORDS = "one two three four five six seven eight nine ten eleven twelve".split()
_TIME_CUE = re.compile(
    r"\d|\b(?:"
    + "|".join(_NUMBER_WORDS)
    + r"|o'clock|morning|afternoon|evening|night|noon|midnight|"
    r"midday|dawn|dusk|sunset|sunrise|today|yesterday|tomorrow|to-night|to-morrow|to-day|tonight|"
    r"o['’]clock|early|late|earlier|quarter|half|past|presently|meanwhile|instant|fortnight|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"day|days|week|weeks|month|months|year|years|hour|hours|minute|minutes|moment|time|ago|"
    r"before|after|since|until|till|during|while|when|once|twice|then|later|soon|"
    r"breakfast|luncheon|lunch|dinner|supper|tea|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
)
_MAX_TIME_TOKENS = 9
_NOT_NAMES = DETERMINERS | PRONOUNS | TITLES | frozenset("his her him hers theirs".split())


@dataclass
class RepairReport:
    events: int = 0
    claims: int = 0
    participants_added: int = 0
    participants_dropped: int = 0
    polarity_changed: int = 0
    in_speech_changed: int = 0
    in_speech_not_located: int = 0
    time_inherited: int = 0
    place_inherited: int = 0
    time_not_temporal: int = 0
    place_not_a_place: int = 0
    about_person_nulled: int = 0
    about_place_nulled: int = 0
    about_time_nulled: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def count(self, code: str) -> None:
        self.reasons[code] = self.reasons.get(code, 0) + 1

    def merge(self, other: RepairReport) -> None:
        for k, v in other.__dict__.items():
            if k == "reasons":
                for c, n in v.items():
                    self.reasons[c] = self.reasons.get(c, 0) + n
            else:
                setattr(self, k, getattr(self, k) + v)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["reasons"] = dict(sorted(self.reasons.items()))
        return d


# --- text helpers


def _contains(hay: str, needle: str) -> bool:
    """Token-bounded substring test on folded strings."""
    return bool(needle) and f" {needle} " in f" {hay} "


def _find(hay: str, needle: str) -> int:
    return f" {hay} ".find(f" {needle} ") if needle else -1


def quotation_spans(text: str) -> list[tuple[int, int]]:
    """Character spans [start, end) of double-quoted speech in `text`, quote marks excluded.

    Curly (“ ”) and straight (") marks. A paragraph that opens with a quote mark while a quote is
    still open continues it (Gutenberg convention for multi-paragraph speech); a quote left open at
    the end of a paragraph that does not continue is closed there. A chunk whose first mark is a
    closing curly mark starts inside a quote that opened before the chunk. Single quotes are
    ignored (apostrophes, nested quotations).
    """
    first = next((ch for ch in text if ch in '“”"'), "")
    inside = first == "”"
    start = 0 if inside else -1
    spans: list[tuple[int, int]] = []
    pos = prev_end = 0
    seen_para = False
    for para in text.split("\n"):
        base = pos
        pos += len(para) + 1
        if not para.strip():
            continue
        lead = base + len(para) - len(para.lstrip())
        if inside and seen_para and text[lead] not in '“"':  # open quote, not continued
            spans.append((start, prev_end))
            inside, start = False, -1
        seen_para = True
        prev_end = base + len(para.rstrip())
        for off, ch in enumerate(para):
            i = base + off
            if ch == "“" or (ch == '"' and not inside):
                if not inside:
                    inside, start = True, i + 1
            elif (ch == "”" or ch == '"') and inside and not (ch == '"' and i == lead):
                spans.append((start, i))
                inside, start = False, -1
    if inside:
        spans.append((start, prev_end))
    return [(a, b) for a, b in spans if b > a]


class _ChunkIndex:
    """Locates quotes in the chunk (typography-insensitive) and tests quotation spans."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.norm = ground_normalise(text)
        self.spans = quotation_spans(text)

    def locate(self, quote: str) -> tuple[int, int] | None:
        q = ground_normalise(quote.strip()).text
        if not q:
            return None
        p = self.norm.text.find(q)
        if p < 0:
            return None
        return self.norm.idx[p], self.norm.ends[p + len(q) - 1]

    def in_speech(self, quote: str) -> bool | None:
        loc = self.locate(quote)
        if loc is None:
            return None
        a, b = loc
        return any(s <= a and b <= e for s, e in self.spans)


class _People:
    """Person mention keys of one chunk: folded name/alias/unique surname -> entity index."""

    def __init__(self, entities: list[dict[str, Any]]) -> None:
        self.names: list[str] = []
        keys: dict[str, set[int]] = defaultdict(set)
        for ei, e in enumerate(entities):
            if e.get("type") != "person":
                continue
            self.names.append(e["name"])
            for surface in [e["name"], *e.get("aliases", [])]:
                for k in self._keys(surface, with_surname=surface == e["name"]):
                    keys[k].add(ei)
        self.entities = entities
        self.key_to_ent = {k: next(iter(v)) for k, v in keys.items() if len(v) == 1}

    @staticmethod
    def _keys(surface: str, *, with_surname: bool) -> list[str]:
        k = normalize_name(surface)
        toks = k.split()
        if not toks or all(t in _NOT_NAMES for t in toks):
            return []
        out = [k] if not (len(toks) == 1 and len(k) < 3) else []
        if with_surname and len(toks) >= 2 and toks[0] not in DETERMINERS:
            if len(toks[-1]) >= 3 and toks[-1] not in _NOT_NAMES:
                out.append(toks[-1])
        return out

    def entity_of(self, name: str) -> int | None:
        for k in self._keys(name, with_surname=True):
            if k in self.key_to_ent:
                return self.key_to_ent[k]
        return None

    def mentioned(self, folded_text: str) -> list[int]:
        """Entity indices mentioned in the text, in order of first mention."""
        hits: dict[int, int] = {}
        for k, ei in self.key_to_ent.items():
            p = _find(folded_text, k)
            if p >= 0 and (ei not in hits or p < hits[ei]):
                hits[ei] = p
        return [ei for ei, _ in sorted(hits.items(), key=lambda x: (x[1], x[0]))]


class _Places:
    def __init__(self, entities: list[dict[str, Any]]) -> None:
        self.groups: list[set[str]] = []
        self.all_keys: set[str] = set()
        for e in entities:
            if e.get("type") == "place":
                ks = {normalize_name(s, "place") for s in [e["name"], *e.get("aliases", [])]}
                self.groups.append({k for k in ks if k})
                self.all_keys |= self.groups[-1]

    def keys(self, place: str) -> set[str]:
        k = normalize_name(place, "place")
        out = {k} if k else set()
        for g in self.groups:
            if k in g:
                out |= g
        return out


# --- per item rules


def _is_name(normalised: str) -> bool:
    toks = normalised.split()
    return bool(toks) and not all(t in _NOT_NAMES for t in toks)


def _is_time_expression(expr: str, quote: str) -> bool:
    """A temporal expression, not a copy of the quote or a noun: has a time cue, is short and is
    not the whole quote."""
    e = fold_text(expr)
    return (
        bool(_TIME_CUE.search(e)) and len(e.split()) <= _MAX_TIME_TOKENS and e != fold_text(quote)
    )


_PLACE_NOUNS = frozenset(
    "room rooms house home hotel lodge station village town city street road lane path wood woods "
    "field fields meadow meadows pool garden grounds kitchen hall office shop inn farm park square "
    "palace church bridge cottage bedroom parlour library courts mansion mansions".split()
)


def _is_place_expression(place: str, chunk_text: str, places: _Places) -> bool:
    """A place name: a place entity of the chunk, a locative noun ('the room', 'the station') or
    a capitalised name that occurs in the chunk (rejects 'the chair', 'fire', 'before me')."""
    if any(k in places.all_keys for k in places.keys(place)):
        return True
    toks = [t for t in re.findall(r"[A-Za-z][\w'-]*", place) if t.casefold() not in _NOT_NAMES]
    if any(t.casefold() in _PLACE_NOUNS for t in toks):
        return True
    return any(re.search(rf"\b{re.escape(t.capitalize())}\b", chunk_text) for t in toks)


def _model_value(item: dict[str, Any], field_: str, audit: str) -> Any:
    """The model's own value: the audit copy if this item was repaired before."""
    return item[audit] if item.get("repair_version") else item.get(field_)


def _repair_event(
    ev: dict[str, Any], people: _People, places: _Places, chunk: _ChunkIndex, rep: RepairReport
) -> None:
    rep.events += 1
    codes: list[str] = []
    m_part = list(_model_value(ev, "participants", "participants_model") or [])
    m_speech = bool(_model_value(ev, "in_speech", "in_speech_model"))
    m_time = _model_value(ev, "time_text", "time_text_model")
    m_place = _model_value(ev, "place", "place_model")
    ev["participants_model"], ev["in_speech_model"] = m_part, m_speech
    ev["time_text_model"], ev["place_model"] = m_time, m_place
    own_raw = f"{ev['quote']} {ev.get('description', '')}"
    own = fold_text(own_raw)

    # R1 participants
    mentioned = people.mentioned(own)
    kept: list[str] = []
    seen_ent: set[int] = set()
    seen_names: set[str] = set()
    for name in m_part:
        ei = people.entity_of(name)
        k = normalize_name(name)
        ok = (ei is not None and ei in mentioned) or (_is_name(k) and _contains(own, fold_text(k)))
        if not ok or k in seen_names or (ei is not None and ei in seen_ent):
            if not ok:
                rep.participants_dropped += 1
                codes.append("PARTICIPANT_UNGROUNDED_DROPPED")
            continue
        kept.append(name)
        seen_names.add(k)
        if ei is not None:
            seen_ent.add(ei)
    added = 0
    for ei in mentioned:
        if ei not in seen_ent:
            kept.append(people.entities[ei]["name"])
            seen_ent.add(ei)
            added += 1
    if added:
        rep.participants_added += added
        codes.append("PARTICIPANTS_ADDED")
    ev["participants"] = kept

    # R3 in_speech
    located = chunk.in_speech(ev["quote"])
    if located is None:
        rep.in_speech_not_located += 1
        codes.append("IN_SPEECH_QUOTE_NOT_LOCATED")
    speech = bool(located)
    if speech != m_speech:
        rep.in_speech_changed += 1
        codes.append("IN_SPEECH_CHANGED")
    ev["in_speech"] = speech

    # R4 time_text / place
    ev["time_text_inherited"] = ev["place_inherited"] = None
    ev["time_text"] = ev["place"] = None
    if m_time:
        if not _is_time_expression(m_time, ev["quote"]):
            rep.time_not_temporal += 1
            codes.append("TIME_NOT_TEMPORAL")
        elif _contains(own, fold_text(m_time)):
            ev["time_text"] = m_time
        else:
            ev["time_text_inherited"] = m_time
            rep.time_inherited += 1
            codes.append("TIME_INHERITED")
    if m_place:
        if not _is_place_expression(m_place, chunk.text, places):
            rep.place_not_a_place += 1
            codes.append("PLACE_NOT_A_PLACE")
        elif any(_contains(own, k) for k in places.keys(m_place)):
            ev["place"] = m_place
        else:
            ev["place_inherited"] = m_place
            rep.place_inherited += 1
            codes.append("PLACE_INHERITED")
    ev["repair"], ev["repair_version"] = codes, REPAIR_VERSION
    for c in codes:
        rep.count(c)


def has_negation(quote: str) -> bool:
    return bool(_NEGATION.search(quote.casefold().replace("’", "'")))


def _repair_claim(cl: dict[str, Any], people: _People, places: _Places, rep: RepairReport) -> None:
    rep.claims += 1
    codes: list[str] = []
    m_pol = _model_value(cl, "polarity", "polarity_model") or "affirm"
    m_who = _model_value(cl, "about_person", "about_person_model")
    m_where = _model_value(cl, "about_place", "about_place_model")
    m_when = _model_value(cl, "about_time_text", "about_time_text_model")
    cl["polarity_model"], cl["about_person_model"] = m_pol, m_who
    cl["about_place_model"], cl["about_time_text_model"] = m_where, m_when
    own = fold_text(f"{cl['quote']} {cl.get('content', '')}")

    # R2 polarity
    pol = "deny" if has_negation(cl["quote"]) else "affirm"
    if pol != m_pol:
        rep.polarity_changed += 1
        codes.append("POLARITY_CHANGED")
    cl["polarity"] = pol
    cl["about_person"], cl["about_place"], cl["about_time_text"] = m_who, m_where, m_when

    # R5 about_*
    if m_who:
        ei = people.entity_of(m_who)
        grounded = (ei is not None and ei in people.mentioned(own)) or (
            _is_name(normalize_name(m_who)) and _contains(own, normalize_name(m_who))
        )
        spk = cl.get("speaker") or ""
        first = bool(_FIRST_PERSON.search(cl["quote"])) and (
            normalize_name(m_who) == normalize_name(spk)
            or (ei is not None and ei == people.entity_of(spk))
        )
        if not (grounded or first):
            cl["about_person"] = None
            rep.about_person_nulled += 1
            codes.append("ABOUT_PERSON_NOT_IN_QUOTE")
    if m_where and not any(_contains(own, k) for k in places.keys(m_where)):
        cl["about_place"] = None
        rep.about_place_nulled += 1
        codes.append("ABOUT_PLACE_NOT_IN_QUOTE")
    if m_when and not _contains(own, fold_text(m_when)):
        cl["about_time_text"] = None
        rep.about_time_nulled += 1
        codes.append("ABOUT_TIME_NOT_IN_QUOTE")
    cl["repair"], cl["repair_version"] = codes, REPAIR_VERSION
    for c in codes:
        rep.count(c)


def repair_items(items: Items, chunk_text: str) -> tuple[Items, RepairReport]:
    """Repair the item dicts of one chunk (the form `ChunkResult.extraction` keeps). Returns a new
    dict; the input is not modified."""
    out: Items = {k: [dict(i) for i in v] for k, v in items.items()}
    rep = RepairReport()
    ents = out.get("entities", [])
    people, places, chunk = _People(ents), _Places(ents), _ChunkIndex(chunk_text)
    for ev in out.get("events", []):
        _repair_event(ev, people, places, chunk, rep)
    for cl in out.get("claims", []):
        _repair_claim(cl, people, places, rep)
    return out, rep


def repair_extraction(
    extraction: schema_v2.Extraction, chunk_text: str
) -> tuple[schema_v2.Extraction, RepairReport]:
    """Validated-model form of `repair_items`."""
    items = {k: [i.model_dump() for i in getattr(extraction, k)] for k in schema_v2.ITEM_MODELS}
    fixed, rep = repair_items(items, chunk_text)
    return schema_v2.Extraction.model_validate(fixed), rep
