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
# Story days of curated day keys: above the weekday scale (0..6) and the heuristic presence days
# (TEXT_DAY_BASE 10000 + n), far below real date ordinals (about 740000): never equal to either.
CURATED_DAY_BASE = 20_000
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

Slot = Literal["person", "place", "time"]


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

    @field_validator("person", "place", "quote", "curated_by", "note")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> CuratedFact:
        if self.source == "speech" and not self.speaker:
            raise ValueError("a speech fact needs a speaker")
        if self.source == "narrator" and self.speaker:
            raise ValueError("a narrator fact has no speaker")
        if self.polarity == "deny" and self.source != "speech":
            raise ValueError("a denial is a claim: it needs source 'speech' and a speaker")
        if self.day_key is not None and self.time_text is None:
            raise ValueError("day_key without time_text: the day applies to a timed event")
        return self
