"""Interval arithmetic on the absolute axis t = day * 1440 + minute (spec 1.1, 4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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


def abs_bounds(t: TimeSpec | None) -> tuple[int, int] | None:
    """Outer bounds on the absolute axis, None unless day, lo and hi are all known."""
    if t is None or t.day is None or t.lo is None or t.hi is None:
        return None
    return t.day * DAY + t.lo, t.day * DAY + t.hi


def has_any_time(t: TimeSpec | None) -> bool:
    return t is not None and not (t.day is None and t.lo is None and t.hi is None)


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Half-open for two proper intervals, closed as soon as one is an instant."""
    if a[0] < a[1] and b[0] < b[1]:
        return a[0] < b[1] and b[0] < a[1]
    return a[0] <= b[1] and b[0] <= a[1]


def compare(a: TimeSpec | None, b: TimeSpec | None) -> TimeCmp:
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


def fmt_span(t: TimeSpec | None) -> str:
    if t is None:
        return "no time"
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
