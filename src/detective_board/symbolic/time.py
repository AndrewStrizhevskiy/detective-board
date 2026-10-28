"""Interval arithmetic on the absolute axis t = day * 1440 + minute (spec 1.1, 4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from detective_board.extract.curated_schema import MOMENT_PREFIX, moment_label
from detective_board.symbolic.model import TimeSpec

DAY = 1440


class TimeRel(StrEnum):
    OVERLAP = "OVERLAP"  # DEF_OVERLAP
    DISJOINT = "DISJOINT"  # DEF_DISJOINT
    UNDECIDED = "UNDECIDED"


@dataclass(frozen=True)
class TimeCmp:
    rel: TimeRel
    possible_overlap: bool = False
    intersection: tuple[int, int] | None = None
    moment: str | None = None  # label of the shared relative moment, if the overlap is one


def is_moment(t: TimeSpec | None) -> bool:
    """A curated relative time: "at the moment <named event>", no clock and no day. It lives on no
    axis, so it can never be ordered against or intersected with a clock time; the only thing the
    layer knows about it is that two facts with the same reference are the same moment."""
    return (
        t is not None
        and t.rel == "at"
        and t.ref_event_id is not None
        and t.ref_event_id.startswith(MOMENT_PREFIX)
    )


def abs_bounds(t: TimeSpec | None) -> tuple[int, int] | None:
    """Outer bounds on the absolute axis, None unless day, lo and hi are all known."""
    if is_moment(t):
        return None
    if t is None or t.day is None or t.lo is None or t.hi is None:
        return None
    return t.day * DAY + t.lo, t.day * DAY + t.hi


def has_any_time(t: TimeSpec | None) -> bool:
    if is_moment(t):
        return True
    return t is not None and not (t.day is None and t.lo is None and t.hi is None)


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Half-open for two proper intervals, closed as soon as one is an instant."""
    if a[0] < a[1] and b[0] < b[1]:
        return a[0] < b[1] and b[0] < a[1]
    return a[0] <= b[1] and b[0] <= a[1]


def compare(a: TimeSpec | None, b: TimeSpec | None) -> TimeCmp:
    if is_moment(a) or is_moment(b):
        # same named moment = the same instant (explicit, curated relation); anything else
        # (another moment, a clock time) is not comparable, never "disjoint"
        if a is not None and b is not None and is_moment(a) and a.ref_event_id == b.ref_event_id:
            return TimeCmp(TimeRel.OVERLAP, True, None, moment_label(a.ref_event_id))
        return TimeCmp(TimeRel.UNDECIDED)
    ba, bb = abs_bounds(a), abs_bounds(b)
    if a is None or b is None or ba is None or bb is None:
        return TimeCmp(TimeRel.UNDECIDED)
    if not overlaps(ba, bb):
        return TimeCmp(TimeRel.DISJOINT)
    if a.exact and b.exact:
        return TimeCmp(TimeRel.OVERLAP, True, (max(ba[0], bb[0]), min(ba[1], bb[1])))
    return TimeCmp(TimeRel.UNDECIDED, True)


def strictly_before(a: TimeSpec | None, b: TimeSpec | None) -> bool:
    """A.hi < B.lo on the absolute axis (touching spans are not ordered)."""
    ba, bb = abs_bounds(a), abs_bounds(b)
    return ba is not None and bb is not None and ba[1] < bb[0]


def fmt_abs(t: int) -> str:
    day, minute = divmod(t, DAY)
    return f"d{day} {minute // 60:02d}:{minute % 60:02d}"


def _clock(m: int | None) -> str:
    return "?" if m is None else f"{m // 60:02d}:{m % 60:02d}"


def fmt_human(t: TimeSpec | None, day_label: str | None = None) -> str:
    """User-visible time: the clock time plus a human day label, never a synthetic day number.
    `day_label` is given for curated day keys and assumed days; without it the day is "day unknown"
    (or "day set from the text" when the day is known but has no human name)."""
    if t is None:
        return "no time"
    if is_moment(t):
        return f"at the moment {moment_label(t.ref_event_id)}, relative time"
    clock = _clock(t.lo) if t.lo == t.hi else f"{_clock(t.lo)}-{_clock(t.hi)}"
    if t.lo is not None and t.hi is not None and not t.exact and t.lo != t.hi:
        clock += " (fuzzy)"
    if day_label:
        return f"{day_label}, {clock}"
    return f"{clock}, day unknown" if t.day is None else f"{clock}, day set from the text"


def fmt_span(t: TimeSpec | None) -> str:
    if t is None:
        return "no time"
    if is_moment(t):
        return f"at the moment {moment_label(t.ref_event_id)} (relative)"
    b = abs_bounds(t)
    if b is None:
        day = "d?" if t.day is None else f"d{t.day}"
        lo = "?" if t.lo is None else f"{t.lo // 60:02d}:{t.lo % 60:02d}"
        hi = "?" if t.hi is None else f"{t.hi // 60:02d}:{t.hi % 60:02d}"
        return f"{day} {lo}-{hi} (partial)"
    kind = "" if t.exact else " (fuzzy)"
    if b[0] == b[1]:
        return f"{fmt_abs(b[0])}{kind}"
    return f"{fmt_abs(b[0])}-{fmt_abs(b[1])}{kind}"
