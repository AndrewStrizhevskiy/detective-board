"""Extraction schema v2: a backward-compatible superset of v1 (docs/backlog.md R-07).

Every v2 model subclasses its v1 model and only adds OPTIONAL fields with defaults, so any v1
payload validates as v2 and `to_v1` is a plain projection. The additions are the minimum the
symbolic rules need (docs/symbolic-layer.md 1.2): a structured claim proposition (who/where/when
and polarity) instead of free text, `in_speech`/`transit` flags on events, `unnamed` on entities.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import Field

from detective_board.extract import schema as v1
from detective_board.extract.schema import Relation, _inline_refs

SCHEMA_VERSION = "2"

Polarity = Literal["affirm", "deny"]

# Fields written by `extract/repair.py` (docs/symbolic-layer.md 11.2): the model never sets them, so
# they are not in the schema sent to Ollama (`ollama_format_schema`) and are stripped from model
# output (`parse.validate_items`). They carry the model's original values (audit) and the grounding
# outcome. The repair version is deliberately not part of the cache key.
REPAIR_FIELDS: dict[str, frozenset[str]] = {
    "entities": frozenset(),
    "events": frozenset(
        "participants_model in_speech_model time_text_model place_model time_text_inherited "
        "place_inherited repair repair_version".split()
    ),
    "claims": frozenset(
        "polarity_model about_person_model about_place_model about_time_text_model "
        "repair repair_version".split()
    ),
    "relations": frozenset(),
}


class Entity(v1.Entity):
    unnamed: bool = Field(
        default=False, description="true if the person/thing has no name, e.g. 'the deceased'"
    )


class Event(v1.Event):
    in_speech: bool = Field(
        default=False, description="true if the event is reported inside someone's quoted speech"
    )
    transit: bool = Field(
        default=False, description="true if it is movement (arrived, left), not being somewhere"
    )
    # --- repair audit (not model-facing, see REPAIR_FIELDS)
    participants_model: list[str] | None = None
    in_speech_model: bool | None = None
    time_text_model: str | None = None
    place_model: str | None = None
    time_text_inherited: str | None = None  # model time not found in the event's own quote
    place_inherited: str | None = None  # model place not found in the event's own quote
    repair: list[str] = Field(default_factory=list)
    repair_version: str | None = None


class Claim(v1.Claim):
    about_person: str | None = Field(
        default=None, description="Who the claim is about (often the speaker)"
    )
    about_place: str | None = Field(default=None, description="Place the claim says someone was at")
    about_time_text: str | None = Field(default=None, description="Time in the claim, as written")
    polarity: Polarity = Field(default="affirm", description="'deny' if the speaker denies it")
    # --- repair audit (not model-facing, see REPAIR_FIELDS)
    polarity_model: Polarity | None = None
    about_person_model: str | None = None
    about_place_model: str | None = None
    about_time_text_model: str | None = None
    repair: list[str] = Field(default_factory=list)
    repair_version: str | None = None


class Extraction(v1.Extraction):
    entities: list[Entity] = Field(default_factory=list)  # type: ignore[assignment]
    events: list[Event] = Field(default_factory=list)  # type: ignore[assignment]
    claims: list[Claim] = Field(default_factory=list)  # type: ignore[assignment]
    relations: list[Relation] = Field(default_factory=list)


ITEM_MODELS: dict[str, type] = {
    "entities": Entity,
    "events": Event,
    "claims": Claim,
    "relations": Relation,
}


def ollama_format_schema() -> dict:
    """JSON schema for Ollama's `format` parameter (v2), with $defs/$ref inlined."""
    s = Extraction.model_json_schema()
    out = cast("dict[Any, Any]", _inline_refs(s, s.get("$defs", {})))
    for kind, hidden in REPAIR_FIELDS.items():
        item = out["properties"][kind]["items"]
        for f in hidden:
            item["properties"].pop(f, None)
    return out


def to_v1(ex: Extraction) -> v1.Extraction:
    """Project a v2 extraction onto v1 (drops the v2-only fields)."""
    keep = {
        "entities": set(v1.Entity.model_fields),
        "events": set(v1.Event.model_fields),
        "claims": set(v1.Claim.model_fields),
        "relations": set(v1.Relation.model_fields),
    }
    data = {k: [i.model_dump(include=keep[k]) for i in getattr(ex, k)] for k in keep}
    return v1.Extraction.model_validate(data)


def from_v1(ex: v1.Extraction) -> Extraction:
    return Extraction.model_validate(ex.model_dump())
