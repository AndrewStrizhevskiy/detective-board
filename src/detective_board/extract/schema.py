"""Extraction schema (v1) for one text chunk.

Deliberately flat and small so a 4-8B model can fill it under constrained decoding:
- entities are Person/Place/Item (one model, `type` discriminates);
- events, claims and relations reference entities by plain-string name (no ids);
- every item carries a `quote`: a verbatim span copied from the chunk (grounding check).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entity(_Base):
    name: str = Field(description="Most complete name as written in the chunk")
    type: Literal["person", "place", "item"]
    aliases: list[str] = Field(
        default_factory=list, description="Other surface forms in the chunk (e.g. 'Holmes')"
    )
    quote: str = Field(description="Verbatim span from the chunk mentioning the entity")


class Event(_Base):
    description: str = Field(description="What happened, one short sentence")
    time_text: str | None = Field(default=None, description="Time as written, e.g. 'nine o'clock'")
    place: str | None = Field(default=None, description="Place name as in entities")
    participants: list[str] = Field(default_factory=list, description="Person names")
    quote: str


class Claim(_Base):
    speaker: str = Field(description="Who asserts it (person name)")
    content: str = Field(description="What is asserted, one short sentence")
    about: str | None = Field(default=None, description="Main entity the claim concerns")
    quote: str


class Relation(_Base):
    subject: str
    predicate: str = Field(description="Short lowercase verb phrase, e.g. 'son of', 'employs'")
    object: str
    quote: str


class Extraction(_Base):
    entities: list[Entity] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


def _inline_refs(node, defs):
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline_refs(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def ollama_format_schema() -> dict:
    """JSON schema for Ollama's `format` parameter, with $defs/$ref inlined."""
    s = Extraction.model_json_schema()
    return _inline_refs(s, s.get("$defs", {}))
