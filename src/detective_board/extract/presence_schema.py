"""Schema of the targeted PRESENCE extraction pass (docs/symbolic-layer.md 11.3).

Kept free of other detective_board imports so the graph layer can import it (like `extract.schema`).
`PresenceFact` is what the model fills; `GroundedFact` is what survives deterministic grounding and
is ingested (extra audit fields the model never sees).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from detective_board.extract.schema import _inline_refs

SCHEMA_VERSION = "presence-1"
SCHEMA_VERSION_V2 = "presence-2"  # person/place chosen from candidate lists (enum in the schema)
UNKNOWN = "UNKNOWN"
MAX_FACTS = 6

Polarity = Literal["affirm", "deny"]
Source = Literal["narrator", "speech"]
Resolution = Literal["quote", "context"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PresenceFact(_Base):
    person: str = Field(description="Person's name exactly as written in the quote")
    place: str = Field(description="Place name or locative noun phrase exactly as in the quote")
    time_text: str = Field(description="Time expression exactly as in the quote")
    day_text: str | None = Field(
        default=None,
        description="Which day, as written in the quote (that night, on Monday); omit if absent",
    )
    polarity: Polarity = Field(
        default="affirm", description="'deny' if the quote says the person was NOT there"
    )
    source: Source = Field(
        default="narrator", description="'speech' if the quote is inside someone's quoted words"
    )
    speaker: str | None = Field(
        default=None, description="Who says it, if source is speech; omit otherwise"
    )
    quote: str = Field(description="Verbatim contiguous span (one or two sentences) of the passage")


class PresenceExtraction(_Base):
    facts: list[PresenceFact] = Field(default_factory=list)


def ollama_format_schema(
    people: Sequence[str] | None = None, places: Sequence[str] | None = None
) -> dict:
    """JSON schema for Ollama's `format` parameter, with $defs/$ref inlined and a 6-fact cap.

    With candidate lists (presence-2) `person` and `place` become enums of the list plus the literal
    UNKNOWN (an empty list leaves just UNKNOWN). Without them the schema is the presence-1 one."""
    s = PresenceExtraction.model_json_schema()
    out = cast("dict[Any, Any]", _inline_refs(s, s.get("$defs", {})))
    out["properties"]["facts"]["maxItems"] = MAX_FACTS
    props = out["properties"]["facts"]["items"]["properties"]
    for field_name, names in (("person", people), ("place", places)):
        if names is not None:
            enum = [n for n in dict.fromkeys(names) if n != UNKNOWN] + [UNKNOWN]
            props[field_name] = {
                "type": "string",
                "enum": enum,
                "description": f"One name from the list, or {UNKNOWN} if the passage is unclear",
            }
    return out


class GroundedFact(BaseModel):
    """A presence fact after grounding. `context` lists fields NOT found in the quote that were
    kept anyway (lenient mode only); strict mode never fills it."""

    model_config = ConfigDict(extra="forbid")

    person: str
    place: str
    time_text: str
    day_text: str | None = None
    polarity: Polarity = "affirm"
    source: Source = "narrator"
    speaker: str | None = None
    quote: str
    context: list[str] = Field(default_factory=list)
    # how person/place were found: 'quote' (literally in the quote) or 'context' (chosen from the
    # candidate list / kept by --lenient without being in the quote: LOW confidence downstream)
    version: str = SCHEMA_VERSION  # presence-1 or presence-2 (candidate lists)
    person_resolution: Resolution = "quote"
    place_resolution: Resolution = "quote"
    codes: list[str] = Field(default_factory=list)  # grounding reason codes (audit)
    model_values: dict[str, Any] = Field(default_factory=dict)  # the model's original fields
    # verification (extract/presence_verify.py): the verifier's answer, its prompt version and the
    # fields that were nulled (LOW, via `context`) when a 'partly' verdict was accepted; None = the
    # fact was not verified. `votes`/`samples`: agreement count of --samples N self-consistency.
    verify: dict[str, Any] | None = None
    votes: int | None = None
    samples: int | None = None
