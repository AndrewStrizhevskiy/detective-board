"""FactBase: immutable, order-normalised snapshot the rules read (spec sections 1, 7)."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, field_validator

from detective_board.symbolic.model import (
    _M,
    RULE_VERSIONS,
    Anchor,
    Confidence,
    FactSource,
    TimeSpec,
)

# Fixed list of motion verbs: an event starting with one may be transit, not presence (spec R1).
MOTION_VERBS = frozenset(
    "went walked ran drove rode travelled traveled hurried left arrived came returned".split()
)


def _sort_anchors(v: list[Anchor]) -> list[Anchor]:
    return sorted(v, key=lambda a: (a.story, a.char_start, a.char_end, a.chunk_id, a.quote))


class PlaceRec(_M):
    id: str
    name: str
    aliases: list[str] = []
    parent_id: str | None = None

    @field_validator("aliases")
    @classmethod
    def _sorted(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


class EventRec(_M):
    id: str
    description: str
    time: TimeSpec | None = None
    place_ref: str | None = None  # place id or surface form, resolved via PlaceIndex
    participants: list[str] = []
    anchors: list[Anchor] = []
    confidence: Confidence = "high"
    narrator: bool = True  # False: reported inside a Claim, not established
    occurrence_id: str | None = None  # equal non-None values = same occurrence (dedup guard)
    curated: bool = False  # human-checked fact (extract/curated.py), shown as "(curated)"
    # human wording of the story day for summaries only ("same day: night of the murder",
    # "day 3 (assumed)"); the machine day stays in `time.day`
    day_label: str | None = None

    @field_validator("participants")
    @classmethod
    def _sorted_participants(cls, v: list[str]) -> list[str]:
        return sorted(set(v))

    _anchors_sorted = field_validator("anchors")(_sort_anchors)

    @property
    def eff_confidence(self) -> Confidence:
        low = self.confidence == "low" or (self.time is not None and self.time.confidence == "low")
        return "low" if low else "high"

    @property
    def presence_confidence(self) -> Confidence:
        """Like eff_confidence, but a motion verb also makes presence low."""
        words = self.description.split()
        motion = bool(words) and words[0].lower() in MOTION_VERBS
        return "low" if motion or self.eff_confidence == "low" else "high"


class PresenceProp(_M):
    kind: Literal["presence"] = "presence"
    person_id: str
    place_ref: str
    time: TimeSpec


class OrderProp(_M):
    kind: Literal["order"] = "order"
    before_event_id: str
    after_event_id: str


Prop = Annotated[PresenceProp | OrderProp, Field(discriminator="kind")]


class ClaimRec(_M):
    id: str
    speaker_id: str
    content: str
    prop: Prop | None = None
    anchors: list[Anchor] = []
    confidence: Confidence = "high"
    curated: bool = False

    _anchors_sorted = field_validator("anchors")(_sort_anchors)


class FactBase(_M):
    story: str = ""
    places: list[PlaceRec] = []
    events: list[EventRec] = []
    claims: list[ClaimRec] = []

    @field_validator("places", "events", "claims")
    @classmethod
    def _sorted_by_id(cls, v: list) -> list:
        return sorted(v, key=lambda r: r.id)

    def event(self, event_id: str) -> EventRec | None:
        return next((e for e in self.events if e.id == event_id), None)

    def claim(self, claim_id: str) -> ClaimRec | None:
        return next((c for c in self.claims if c.id == claim_id), None)

    def digest(self) -> str:
        """sha256 over canonical JSON of all facts plus rule versions."""
        payload = {"facts": self.model_dump(mode="json"), "rules": RULE_VERSIONS}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_facts(source: FactSource, story: str) -> FactBase:
    """The only I/O entry point; the adapter behind `source` does the reading."""
    return source.load(story)
