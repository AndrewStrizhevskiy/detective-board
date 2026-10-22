"""Hand-built mini graphs. Times are written as day + "HH:MM"; every event carries a real quote."""

from __future__ import annotations

from detective_board.symbolic.api import (
    Anchor,
    ClaimRec,
    EventRec,
    FactBase,
    OrderProp,
    PlaceRec,
    PresenceProp,
    TimeSpec,
)

CHUNKS: dict[str, str] = {}


def hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def anchor(fid: str) -> Anchor:
    quote = f"Quote of {fid}."
    text = f"xx {quote} yy"
    chunk = f"s-{fid}"
    CHUNKS[chunk] = text
    return Anchor(
        story="s",
        chunk_id=chunk,
        char_start=1000 + 3,
        char_end=1000 + 3 + len(quote),
        quote=quote,
        rel_start=3,
        rel_end=3 + len(quote),
    )


def span(
    day: int | None,
    lo: str | None,
    hi: str | None = None,
    *,
    exact: bool = True,
    conf: str = "high",
    **kw,
) -> TimeSpec:
    lo_m = None if lo is None else hm(lo)
    hi_m = lo_m if hi is None and lo is not None else (None if hi is None else hm(hi))
    return TimeSpec(day=day, lo=lo_m, hi=hi_m, exact=exact, confidence=conf, **kw)  # type: ignore[arg-type]


def ev(
    eid: str,
    who: str | list[str] | None = "W",
    place: str | None = None,
    time: TimeSpec | None = None,
    *,
    conf: str = "high",
    desc: str | None = None,
    **kw,
) -> EventRec:
    people = [] if who is None else ([who] if isinstance(who, str) else who)
    return EventRec(
        id=eid,
        description=desc or f"{'/'.join(people)} at {place}",
        time=time,
        place_ref=place,
        participants=people,
        anchors=[anchor(eid)],
        confidence=conf,  # type: ignore[arg-type]
        **kw,
    )


def rel_ev(
    eid: str, rel: str, ref: str, *, conf: str = "high", tconf: str = "high", **kw
) -> EventRec:
    """Event without absolute time, ordered relative to `ref`."""
    return ev(
        eid, None, None, TimeSpec(rel=rel, ref_event_id=ref, confidence=tconf), conf=conf, **kw
    )  # type: ignore[arg-type]


def places() -> list[PlaceRec]:
    return [
        PlaceRec(id="B", name="Baker Street", aliases=["Baker St", "X"]),
        PlaceRec(id="H", name="221B", parent_id="B"),
        PlaceRec(id="D", name="Docks", aliases=["X"]),
        PlaceRec(id="L", name="London"),
    ]


def fbase(events=(), claims=(), pl=None) -> FactBase:
    return FactBase(
        story="s", places=places() if pl is None else pl, events=list(events), claims=list(claims)
    )


def claim(cid: str, prop, *, conf: str = "high", speaker: str = "S") -> ClaimRec:
    return ClaimRec(
        id=cid,
        speaker_id=speaker,
        content=f"claim {cid}",
        prop=prop,
        anchors=[anchor(cid)],
        confidence=conf,  # type: ignore[arg-type]
    )


def presence(person: str, place: str, time: TimeSpec) -> PresenceProp:
    return PresenceProp(person_id=person, place_ref=place, time=time)


__all__ = ["OrderProp", "claim", "ev", "fbase", "hm", "places", "presence", "rel_ev", "span"]
