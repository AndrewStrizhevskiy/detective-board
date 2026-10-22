"""Derive a normalised time from `time_text` (graph zone; the extraction LLM never does this).

Small, tested pattern set. Anything else is `unknown`. `confidence` is "low" whenever the result is
a guess: a bare clock hour without am/pm context, a day part, midnight. The story day is never
derived here (the text does not give it); see `GraphStore.set_event_day`.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

TIME_NORM_VERSION = "1"

_WORDS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve".split()
    )
}
_MIN_WORDS = {
    "five": 5,
    "ten": 10,
    "twenty": 20,
    "twenty five": 25,
    "twenty-five": 25,
    "twentyfive": 25,
    "two": 2,
    "three": 3,
    "four": 4,
}
_HOUR = r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d{1,2})"
_QUAL = (
    r"(?:\s*(?:(?P<mer>a\.?\s?m\.?|p\.?\s?m\.?)|(?:in the|at|of the|during the)?\s*"
    r"(?P<part>morning|forenoon|afternoon|evening|night)))?"
)
DAY_PARTS: dict[str, tuple[int, int]] = {
    "morning": (360, 720),
    "afternoon": (720, 1080),
    "evening": (1080, 1320),
    "night": (1320, 1440),
}


class TimeNorm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    time_text: str | None = None
    method: Literal["clock", "noon", "midnight", "day_part", "unknown"] = "unknown"
    lo: int | None = None
    hi: int | None = None
    exact: bool = False
    confidence: Literal["high", "low"] = "low"
    matched: str | None = None


def _hour_val(tok: str) -> int | None:
    v = int(tok) if tok.isdigit() else _WORDS.get(tok)
    return v if v is not None and 0 <= v <= 24 else None


def _to_24h(h: int, mer: str | None, part: str | None) -> tuple[int, bool]:
    """(hour in 24h, certain?). Hours above 12 are already 24h."""
    if h > 12:
        return h % 24, True
    if mer:
        pm = mer.replace(".", "").replace(" ", "") == "pm"
        return (h % 12) + (12 if pm else 0), True
    if part in ("morning", "forenoon"):
        return h % 12, True
    if part in ("afternoon", "evening"):
        return (h % 12) + 12, True
    if part == "night":
        if h == 12:
            return 0, False  # midnight: which day is unclear
        return (h + 12 if h >= 6 else h), True
    return h, False  # bare hour: taken as written, a guess


def _clock(hour: str, minute: int, delta: int, m: re.Match, text: str) -> TimeNorm:
    h = _hour_val(hour)
    if h is None:
        return TimeNorm(time_text=text)
    h24, certain = _to_24h(h, m.groupdict().get("mer"), m.groupdict().get("part"))
    t = h24 * 60 + minute + delta
    if t < 0:  # e.g. "five minutes to twelve at night": previous day, so a guess
        t, certain = t + 1440, False
    return TimeNorm(
        time_text=text,
        method="clock",
        lo=t,
        hi=t,
        exact=True,
        confidence="high" if certain else "low",
        matched=m.group(0).strip(),
    )


def _minutes(tok: str) -> int | None:
    tok = tok.replace("-", " ")
    if tok.isdigit():
        return int(tok)
    return _MIN_WORDS.get(tok)


def derive_time_norm(time_text: str | None) -> TimeNorm:
    """Pattern-based normalisation; `unknown` (lo=hi=None, low) when no pattern fits."""
    if time_text is None or not time_text.strip():
        return TimeNorm(time_text=time_text)
    t = " ".join(time_text.casefold().replace("’", "'").split())
    tt = t.replace("half-past", "half past")

    m = re.search(rf"\bhalf past {_HOUR}{_QUAL}", tt)
    if m:
        return _clock(m.group(1), 0, 30, m, time_text)
    m = re.search(rf"\ba quarter (to|past) {_HOUR}{_QUAL}", tt)
    if m:
        return _clock(m.group(2), 0, -15 if m.group(1) == "to" else 15, m, time_text)
    m = re.search(rf"\b(\d+|[a-z-]+(?: five)?) minutes (to|past) {_HOUR}{_QUAL}", tt)
    if m and (mins := _minutes(m.group(1))) is not None:
        return _clock(m.group(3), 0, -mins if m.group(2) == "to" else mins, m, time_text)
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(?P<mer>a\.?\s?m\.?|p\.?\s?m\.?)?", tt)
    if m and int(m.group(2)) < 60 and int(m.group(1)) <= 24:
        return _clock(m.group(1), int(m.group(2)), 0, m, time_text)
    m = re.search(rf"\b{_HOUR} o'?clock{_QUAL}", tt)
    if m:
        return _clock(m.group(1), 0, 0, m, time_text)
    m = re.search(
        rf"\b{_HOUR}(?:\s*(?P<mer>a\.?\s?m\.?|p\.?\s?m\.?)|\s+(?:in the|at|of the)\s+"
        r"(?P<part>morning|forenoon|afternoon|evening|night))",
        tt,
    )
    if m:
        return _clock(m.group(1), 0, 0, m, time_text)
    if re.search(r"\b(noon|midday)\b", tt):
        return TimeNorm(
            time_text=time_text,
            method="noon",
            lo=720,
            hi=720,
            exact=True,
            confidence="high",
            matched="noon",
        )
    if re.search(r"\bmidnight\b", tt):
        return TimeNorm(
            time_text=time_text,
            method="midnight",
            lo=0,
            hi=0,
            exact=True,
            confidence="low",
            matched="midnight",
        )
    if re.search(r"\b(next|following|previous|tomorrow|yesterday|later|earlier)\b", tt):
        return TimeNorm(time_text=time_text)  # relative to another event: not derivable here
    for part in ("morning", "afternoon", "evening", "night"):
        if re.search(rf"\b{part}\b", tt):
            lo, hi = DAY_PARTS[part]
            return TimeNorm(
                time_text=time_text,
                method="day_part",
                lo=lo,
                hi=hi,
                exact=False,
                confidence="low",
                matched=part,
            )
    return TimeNorm(time_text=time_text)
