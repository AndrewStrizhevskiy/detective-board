"""Deterministic normaliser between extraction and the rules (backlog R-07, R-08, R-11).

Turns free-text times into the `TimeSpec` the rules read, gives events a story day where the text
allows it, and turns schema-v2 claim fields into a `PresenceProp`. No LLM, no clock, no random:
same graph in, same overlays out. Every guess is `low`, so findings resting on it are conditional.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from detective_board.graph.timenorm import DAY_PARTS, derive_time_norm
from detective_board.symbolic.api import PresenceProp, TimeSpec

NORMALISER_VERSION = "2"
# Heuristic story days of presence facts (`assign_text_days`): far from the weekday scale (0..6)
# and from date ordinals (about 730000), so a heuristic day never equals a real one by accident.
TEXT_DAY_BASE = 10_000
SOURCE = "normaliser"

Confidence = Literal["high", "low"]

_APPROX = re.compile(
    r"\b(about|around|nearly|almost|roughly|shortly|towards?|some time|soon after|"
    r"a little (before|after)|or so)\b"
)
_PART = r"(morning|afternoon|evening|night|day)"
_RELATIVE: list[tuple[re.Pattern[str], int, str | None]] = [
    (re.compile(rf"\b(next|following) {_PART}\b|\bthe morrow\b|\btomorrow\b"), 1, "after"),
    (
        re.compile(
            rf"\b{_PART} before\b|\b(previous|preceding) {_PART}\b|\byesterday\b|"
            rf"\bthe night before\b"
        ),
        -1,
        "before",
    ),
    (re.compile(rf"\b(that|the same|that very) {_PART}\b|\blater that day\b"), 0, None),
]
_MONTHS: tuple[str, ...] = tuple(
    "january february march april may june july august september october november december".split()
)
_WEEKDAYS: tuple[str, ...] = tuple(
    "monday tuesday wednesday thursday friday saturday sunday".split()
)
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
_DATE = re.compile(
    rf"\b(?:({'|'.join(_MONTHS)})\s+{_ORD}|{_ORD}\s+(?:of\s+)?({'|'.join(_MONTHS)}))\b"
)
_WEEKDAY = re.compile(rf"\b({'|'.join(_WEEKDAYS)})\b")
_QUALIFIED_WD = re.compile(rf"\b(next|following|last|previous|coming)\s+({'|'.join(_WEEKDAYS)})\b")


def _fold(text: str) -> str:
    return " ".join(text.casefold().replace("’", "'").split())


def _relative(t: str) -> tuple[int, str | None, str | None] | None:
    """(day offset, order relation, part of day) of a relative cue such as 'the next morning'."""
    for pat, offset, rel in _RELATIVE:
        m = pat.search(t)
        if m:
            part = next((p for p in m.groups() if p in DAY_PARTS), None)
            return offset, rel, part
    return None


def normalise_time(
    text: str | None,
    *,
    ref: TimeSpec | None = None,
    ref_event_id: str | None = None,
    inherited: bool = False,
) -> TimeSpec | None:
    """`TimeSpec` for one time expression. `ref` is the time of the event a relative cue
    ('the next morning') refers to; its day is used only when it is known. `inherited` marks an
    expression that is not in the event's own quote (repair step): always low, never exact."""
    if text is None or not text.strip():
        return None
    t = _fold(text)
    rel = _relative(t)
    tn = derive_time_norm(text)
    lo, hi, exact = tn.lo, tn.hi, tn.exact
    low = (
        inherited
        or tn.confidence == "low"
        or bool(_APPROX.search(t))
        or bool(re.search(r"\bsince\b", t))
    )
    if inherited:
        exact = False
    day: int | None = None
    rel_kind: Any = None
    ref_id: str | None = None
    if rel is not None:
        offset, rel_kind, part = rel
        low = True
        if tn.method in ("unknown", "day_part") and part is not None:
            lo, hi = DAY_PARTS[part]
            exact = False
        if ref_event_id is not None:
            ref_id = ref_event_id
            if ref is not None and ref.day is not None:
                day = ref.day + offset
        else:
            rel_kind = None
    return TimeSpec(
        day=day,
        lo=lo,
        hi=hi,
        exact=exact,
        rel=rel_kind,
        ref_event_id=ref_id,
        confidence="low" if low else "high",
        time_text=text,
    )


@dataclass(frozen=True)
class DayInput:
    item_id: str
    text: str | None
    order: int  # position in the story (char offset); used only to pick a relative reference
    known_day: int | None = None  # curated day: kept, and usable as a relative reference
    inherited: bool = False  # text not from the item's own quote: its day is never `high`


@dataclass(frozen=True)
class DayResult:
    day: int | None
    confidence: Confidence
    method: Literal["curated", "date", "weekday", "relative", "day_text", "none"]
    ref_event_id: str | None = None


def _date_ordinal(m: re.Match[str]) -> int | None:
    month = m.group(1) or m.group(4)
    dom = int(m.group(2) or m.group(3))
    try:
        return date(2001, _MONTHS.index(month) + 1, dom).toordinal()  # 2001: not a leap year
    except ValueError:
        return None


def resolve_days(items: Sequence[DayInput]) -> dict[str, DayResult]:
    """Story calendar. Explicit dates are `high`; weekdays are placed through a date named in the
    same expression ('June 3rd, that is, on Monday'), else on their own week scale, `low`.
    A relative cue takes the day of the nearest earlier item with a known day, `low`, because
    the reference is chosen by narration order. Without a cue the day stays unknown."""
    ordered = sorted(items, key=lambda i: (i.order, i.item_id))
    folded = {i.item_id: _fold(i.text or "") for i in ordered}
    dates: dict[str, int] = {}
    weekdays: dict[str, int] = {}
    for i in ordered:
        if (m := _DATE.search(folded[i.item_id])) and (o := _date_ordinal(m)) is not None:
            dates[i.item_id] = o
        # "next Monday", "last Friday": which week is unknown, so no day from the weekday
        if (m := _WEEKDAY.search(folded[i.item_id])) and not _QUALIFIED_WD.search(
            folded[i.item_id]
        ):
            weekdays[i.item_id] = _WEEKDAYS.index(m.group(1))
    link = next(((dates[k], weekdays[k]) for k in dates if k in weekdays), None)
    out: dict[str, DayResult] = {}
    last: tuple[str, int] | None = None
    for i in ordered:
        res = DayResult(None, "low", "none")
        if i.known_day is not None:
            res = DayResult(i.known_day, "low", "curated")
        elif i.item_id in dates:
            res = DayResult(dates[i.item_id], "high", "date")
        elif i.item_id in weekdays:
            wd = weekdays[i.item_id]
            if link is not None:
                delta = (wd - link[1]) % 7
                res = DayResult(link[0] + (delta - 7 if delta > 3 else delta), "low", "weekday")
            elif not dates:
                res = DayResult(wd, "low", "weekday")
        elif (rel := _relative(folded[i.item_id])) is not None:
            res = (
                DayResult(last[1] + rel[0], "low", "relative", last[0])
                if last is not None
                else DayResult(None, "low", "relative")
            )
        if i.inherited and res.confidence == "high":
            res = DayResult(res.day, "low", res.method, res.ref_event_id)
        if res.day is not None:
            last = (i.item_id, res.day)
        out[i.item_id] = res
    return dict(sorted(out.items()))


_DAY_PREPOSITIONS = frozenset("on in upon during at of".split())


def day_key(day_text: str) -> str:
    """Grouping key of a day label: casefolded, punctuation, leading prepositions and the filler
    'very' removed. "That night" and "that very night" share a key; "that night" and "the night"
    do not (kept apart on purpose: they may name different nights)."""
    words = [w for w in re.sub(r"[^\w\s'-]", " ", _fold(day_text)).split() if w != "very"]
    while words and words[0] in _DAY_PREPOSITIONS:
        words.pop(0)
    return " ".join(words)


def assign_text_days(
    days: dict[str, DayResult], day_texts: dict[str, str], order: dict[str, int]
) -> dict[str, DayResult]:
    """HEURISTIC story days for presence facts (extract/presence.py): items of one story whose
    `day_text` has the same `day_key` get the same synthetic day, always `low`. Only items without
    a curated day, an explicit date or a weekday are touched (those keep what `resolve_days`
    gave); a relative cue ("that night") is replaced, because it points at whatever dated item
    came last. Facts that share a label but belong to different nights are not told apart, which
    is why every finding resting on such a day is conditional. Groups are numbered in narration
    order, so the result is deterministic."""
    out = dict(days)
    groups: dict[str, int] = {}
    for k in sorted(day_texts, key=lambda x: (order.get(x, 0), x)):
        if days[k].method in ("curated", "date", "weekday"):
            continue
        key = day_key(day_texts[k])
        if not key:
            continue
        n = groups.setdefault(key, len(groups))
        out[k] = DayResult(TEXT_DAY_BASE + n, "low", "day_text")
    return out


@dataclass(frozen=True)
class PropResult:
    prop: PresenceProp | None
    confidence: Confidence
    reason: str


Resolver = Callable[[str], list[str]]


def claim_prop(
    claim: Any,
    resolve_person: Resolver,
    resolve_place: Resolver,
    *,
    day: int | None,
    day_confidence: Confidence,
) -> PropResult:
    """Schema-v2 claim fields -> `PresenceProp(person, place, time)`. A denial, a missing or
    unparsed slot, or a name that resolves to zero or several ids gives no proposition (R3 then
    reports UNSTRUCTURED_CLAIM); the reason code says which slot failed."""

    def fail(reason: str) -> PropResult:
        return PropResult(None, "low", reason)

    if getattr(claim, "polarity", "affirm") == "deny":
        return fail("DENIAL_NOT_MODELLED")
    who = getattr(claim, "about_person", None)
    if not who:  # "often the speaker" is a guess the rules must not rest on
        return fail("PERSON_MISSING")
    people = resolve_person(who)
    if len(people) != 1:
        return fail("PERSON_AMBIGUOUS" if people else "PERSON_UNRESOLVED")
    where = getattr(claim, "about_place", None)
    if not where:
        return fail("NO_PLACE")
    places = resolve_place(where)
    if len(places) != 1:
        return fail("PLACE_AMBIGUOUS" if places else "PLACE_UNRESOLVED")
    when = getattr(claim, "about_time_text", None)
    t = normalise_time(when)
    if t is None:
        return fail("NO_TIME")
    if t.lo is None and t.day is None:
        return fail("TIME_UNPARSED")
    low = t.confidence == "low" or day is None or day_confidence == "low"
    conf: Confidence = "low" if low else "high"
    t = t.model_copy(update={"day": t.day if t.day is not None else day, "confidence": conf})
    return PropResult(PresenceProp(person_id=people[0], place_ref=places[0], time=t), conf, "OK")


@dataclass(frozen=True)
class NormaliseReport:
    story: str
    events_timed: int
    events_dated: int
    claims_structured: int
    claim_reasons: dict[str, int]


def apply(store: Any, story: str) -> NormaliseReport:
    """Normalise one story in a `GraphStore`: writes overlays `time` and `story_day` on events
    and `prop` on claims (source 'normaliser'). Curated overlays (any other source) are kept."""
    rows = store.conn.execute(
        "SELECT id, kind, props_json, COALESCE(char_start, rel_start, 0) pos FROM g_node"
        " WHERE story=? AND kind IN ('event','claim') ORDER BY chunk_id, pos, id",
        (story,),
    ).fetchall()
    curated = {
        (r["node_id"], r["key"]): (json.loads(r["value_json"]), r["confidence"])
        for r in store.conn.execute(
            "SELECT o.node_id, o.key, o.value_json, o.confidence FROM g_overlay o JOIN g_node n"
            " ON n.id=o.node_id WHERE n.story=? AND o.source != ?",
            (story, SOURCE),
        )
    }
    props = {r["id"]: json.loads(r["props_json"]) for r in rows}
    kind = {r["id"]: r["kind"] for r in rows}
    order = {r["id"]: i for i, r in enumerate(rows)}
    inherited = {k for k in order if kind[k] == "event" and not props[k].get("time_text")}
    text = {
        k: props[k].get("time_text" if kind[k] == "event" else "about_time_text") for k in order
    }
    for k in inherited:  # repair step: model time not found in the event's own quote
        text[k] = props[k].get("time_text_inherited")
    day_texts = {k: props[k]["day_text"] for k in order if props[k].get("day_text")}
    day_src = {  # presence pass: the fact's own day label leads the text the day is read from
        k: f"{day_texts[k]} {text[k] or ''}".strip() if k in day_texts else text[k] for k in order
    }
    known = {k: v[0] for (k, key), v in curated.items() if key == "story_day"}
    days = resolve_days(
        [DayInput(k, day_src[k], order[k], known.get(k), k in inherited) for k in order]
    )
    days = assign_text_days(days, day_texts, order)

    def day_of(node_id: str) -> tuple[int | None, Confidence]:
        cur = curated.get((node_id, "story_day"))
        if cur is not None:
            return cur[0], "high" if cur[1] == "high" else "low"
        return days[node_id].day, days[node_id].confidence

    times: dict[str, TimeSpec] = {}
    for r in rows:
        if r["kind"] != "event":
            continue
        d = days[r["id"]]
        ref_id = d.ref_event_id if kind.get(d.ref_event_id or "") == "event" else None
        t = normalise_time(
            text[r["id"]],
            ref=times.get(ref_id or ""),
            ref_event_id=ref_id,
            inherited=r["id"] in inherited,
        )
        if (r["id"], "time") in curated:  # a curated TimeSpec wins, its day included
            times[r["id"]] = TimeSpec.model_validate(curated[(r["id"], "time")][0])
            continue
        if t is None:
            continue
        day, conf = day_of(r["id"])
        if t.day is None and day is not None:
            low = t.confidence == "low" or conf == "low"
            t = t.model_copy(update={"day": day, "confidence": "low" if low else "high"})
        times[r["id"]] = t
    n_dated = 0
    reasons: dict[str, int] = {}
    n_props = 0
    with store._tx():
        store.conn.execute(
            "DELETE FROM g_overlay WHERE source=? AND node_id IN"
            " (SELECT id FROM g_node WHERE story=?)",
            (SOURCE, story),
        )
        for eid, t in sorted(times.items()):
            n_dated += t.day is not None
            if (eid, "time") in curated:
                continue
            _put(store, eid, "time", t.model_dump(mode="json"), t.confidence)
            if t.day is not None and (eid, "story_day") not in curated:
                _put(store, eid, "story_day", t.day, days[eid].confidence)
        for r in rows:
            if r["kind"] != "claim" or (r["id"], "prop") in curated:
                continue
            day, conf = day_of(r["id"])
            res = claim_prop(
                _ClaimView(props[r["id"]]),
                lambda n: store.resolve(n, story=story, kinds=("person",)),
                lambda n: store.resolve(n, story=story, kinds=("place",)),
                day=day,
                day_confidence=conf,
            )
            reasons[res.reason] = reasons.get(res.reason, 0) + 1
            if res.prop is not None:
                _put(store, r["id"], "prop", res.prop.model_dump(mode="json"), res.confidence)
                n_props += 1
    return NormaliseReport(story, len(times), n_dated, n_props, dict(sorted(reasons.items())))


class _ClaimView:
    """Attribute view over a stored claim's props (the graph keeps the v2 fields there)."""

    def __init__(self, p: dict[str, Any]) -> None:
        self.speaker = p.get("speaker") or ""
        self.about_person = p.get("about_person")
        self.about_place = p.get("about_place")
        self.about_time_text = p.get("about_time_text")
        self.polarity = p.get("polarity") or "affirm"


def main(argv: list[str] | None = None) -> None:
    """python -m detective_board.extract.normalise data/graph/graph.sqlite [--story SLUG ...]"""
    import argparse

    from detective_board.graph import GraphStore

    ap = argparse.ArgumentParser(prog="normalise", description=__doc__)
    ap.add_argument("graph", help="graph SQLite file built by the extraction pipeline")
    ap.add_argument("--story", action="append", help="only these stories (default: all)")
    ns = ap.parse_args(argv)
    store = GraphStore(ns.graph)
    try:
        stories = ns.story or [
            r[0] for r in store.conn.execute("SELECT DISTINCT story FROM g_node ORDER BY story")
        ]
        for story in stories:
            r = apply(store, story)
            print(
                f"{story}: events timed {r.events_timed}, dated {r.events_dated}; "
                f"claims structured {r.claims_structured}; reasons {r.claim_reasons}"
            )
    finally:
        store.close()


def _put(store: Any, node_id: str, key: str, value: Any, confidence: str) -> None:
    store.conn.execute(
        "INSERT OR REPLACE INTO g_overlay(node_id,key,value_json,confidence,source)"
        " VALUES (?,?,?,?,?)",
        (
            node_id,
            key,
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
            confidence,
            SOURCE,
        ),
    )


if __name__ == "__main__":
    main()
