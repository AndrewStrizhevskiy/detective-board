"""Schema of the CURATED presence facts (docs/symbolic-layer.md 11.4).

Curated facts are written and checked by the team (AI-assisted, to be re-checked by a human) for the
demo cases, where the small extraction models do not produce the facts a rule needs (coreference:
"he", "there"). They are NOT the output of the automatic pipeline and are labelled as such wherever
they are shown. Kept free of other detective_board imports so the graph layer can import it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CURATED_SCHEMA_VERSION = "curated-1"
CURATED_MARK = "(curated)"
REVIEW_PENDING = "human re-check pending"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOGIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")


def review_phrase(reviewed_by: str, reviewed_on: str) -> str:
    return f"human re-check done by {reviewed_by} on {reviewed_on}"


# What answers, boards and slides say about the curated files. One value for both files; a test
# (tests/curated/test_review.py) checks it against their reviewed_by / reviewed_on fields.
CURATED_REVIEW = REVIEW_PENDING


def review_status(reviews: list[tuple[str | None, str | None]]) -> str:
    """The phrase CURATED_REVIEW must hold for these (reviewed_by, reviewed_on) pairs: 'pending'
    unless every record was checked."""
    if not reviews or any(by is None for by, _ in reviews):
        return REVIEW_PENDING
    by = " and ".join(sorted({b for b, _ in reviews if b}))
    on = " and ".join(sorted({d for _, d in reviews if d}))
    return review_phrase(by, on)


def check_review(reviewed_by: str | None, reviewed_on: str | None) -> None:
    """Both or neither; a GitHub login and an ISO date (YYYY-MM-DD)."""
    if (reviewed_by is None) != (reviewed_on is None):
        raise ValueError("reviewed_by and reviewed_on go together")
    if reviewed_by is not None and not _LOGIN.match(reviewed_by):
        raise ValueError("reviewed_by must be a GitHub login")
    if reviewed_on is not None and not _DATE.match(reviewed_on):
        raise ValueError("reviewed_on must be YYYY-MM-DD")


# Story days of curated day keys: above the weekday scale (0..6) and the heuristic presence days
# (TEXT_DAY_BASE 10000 + n), far below real date ordinals (about 740000): never equal to either.
CURATED_DAY_BASE = 20_000
# A relative time ("the moment Sir Eustace entered") has no clock and no day. It is a TimeSpec with
# rel "at" and this reference id; the symbolic layer treats it as an explicit same-moment relation
# (docs/symbolic-layer.md 11.4), never as a point on the absolute axis.
MOMENT_PREFIX = "moment:"
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

Slot = Literal["person", "place", "time"]


def moment_id(story: str, time_ref: str) -> str:
    """Reference id of a relative moment: equal for the facts of one story that share `time_ref`."""
    return f"{MOMENT_PREFIX}{story}:{time_ref}"


def moment_label(ref_id: str | None) -> str | None:
    """Human wording of a moment reference id ("moment:abbey-grange:sir-eustace-entered" ->
    "sir eustace entered"); None if `ref_id` is not a moment reference."""
    if ref_id is None or not ref_id.startswith(MOMENT_PREFIX):
        return None
    return ref_id.split(":", 2)[-1].replace("-", " ")


def curated_day(story: str, day_key: str) -> int:
    """Deterministic synthetic story day of a curated day key (same story + key = same day)."""
    h = hashlib.sha256(f"{story}|{day_key}".encode()).hexdigest()
    return CURATED_DAY_BASE + int(h[:8], 16) % 10_000


class CuratedFact(BaseModel):
    """One human-checked "person was / was said to be at a place at a time" statement.

    `quote` must be a verbatim span of `data/clean/<story>.txt` (the loader checks it after
    whitespace and quotation-mark normalisation). `inferred` lists the slots the quote does not
    state itself (a pronoun resolved from the preceding text, a place implied by the narrative):
    such a fact is LOW confidence and the note must say why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    story: str
    person: str = Field(description="Canonical graph-style name, same string for the same person")
    place: str = Field(description="Canonical graph-style place name")
    time_text: str | None = Field(description="Time expression verbatim from the quote, or null")
    day_text: str | None = None
    time_ref: str | None = Field(
        default=None,
        description="Relative time: a slug shared by the facts of one story that the curator "
        "asserts happened at the same moment (instead of time_text)",
    )
    time_ref_text: str | None = Field(
        default=None,
        description="Words of the quote that give the anchor of time_ref, verbatim; null if the "
        "quote does not state it (then 'time' is inferred and the note says why)",
    )
    day_key: str | None = Field(
        default=None, description="Shared story-day key: the same key within a story is one day"
    )
    polarity: Literal["affirm", "deny"] = "affirm"
    source: Literal["narrator", "speech"]
    speaker: str | None = None
    quote: str
    curated_by: str
    note: str
    inferred: list[Slot] = Field(default_factory=list)
    confidence: Literal["high", "low"] | None = Field(
        default=None, description="'low' forces LOW; otherwise the normaliser decides"
    )
    reviewed_by: str | None = Field(default=None, description="GitHub login of the human checker")
    reviewed_on: str | None = Field(default=None, description="Date of the human check")

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("id must be lowercase letters, digits, '-' or '_'")
        return v

    @field_validator("day_key")
    @classmethod
    def _key_ok(cls, v: str | None) -> str | None:
        if v is not None and not _KEY.match(v):
            raise ValueError("day_key must be lowercase kebab-case")
        return v

    @field_validator("time_ref")
    @classmethod
    def _ref_ok(cls, v: str | None) -> str | None:
        if v is not None and not _KEY.match(v):
            raise ValueError("time_ref must be lowercase kebab-case")
        return v

    @field_validator("person", "place", "quote", "curated_by", "note")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> CuratedFact:
        check_review(self.reviewed_by, self.reviewed_on)
        if self.source == "speech" and not self.speaker:
            raise ValueError("a speech fact needs a speaker")
        if self.source == "narrator" and self.speaker:
            raise ValueError("a narrator fact has no speaker")
        if self.polarity == "deny" and self.source != "speech":
            raise ValueError("a denial is a claim: it needs source 'speech' and a speaker")
        if self.time_ref is not None and self.time_text is not None:
            raise ValueError("time_ref and time_text are exclusive: a clock time or a moment")
        if self.time_ref_text is not None and self.time_ref is None:
            raise ValueError("time_ref_text without time_ref")
        if self.day_key is not None and self.time_text is None and self.time_ref is None:
            raise ValueError(
                "day_key without time_text or time_ref: the day applies to a timed event"
            )
        return self
