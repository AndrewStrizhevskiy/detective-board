"""Public result models of the symbolic layer (docs/symbolic-layer.md section 8)."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from detective_board.symbolic.facts import FactBase

RULE_VERSIONS: dict[str, str] = {"R1": "1", "R2": "1", "R3": "1"}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Verdict(StrEnum):
    VIOLATED = "violated"
    CONSISTENT = "consistent"
    UNKNOWN = "unknown"


Confidence = Literal["high", "low"]
Rel = Literal["before", "after", "during", "at"]


class Anchor(_M):
    story: str
    chunk_id: str
    char_start: int
    char_end: int
    quote: str
    rel_start: int | None = None
    rel_end: int | None = None
    ambiguous: bool = False


class TimeSpec(_M):
    day: int | None = None
    lo: int | None = None
    hi: int | None = None
    exact: bool = False
    rel: Rel | None = None
    ref_event_id: str | None = None
    confidence: Confidence = "low"
    time_text: str | None = None


class FactRef(_M):
    fact_id: str
    kind: Literal["event", "claim", "entity", "order", "relation", "derived"]
    provenance: Literal["extracted", "derived"]
    confidence: Confidence | None
    summary: str
    anchors: list[Anchor]


class EdgeRef(_M):
    edge_id: int | str
    rel: str
    src: str
    dst: str
    anchors: list[Anchor]


class Step(_M):
    step: int
    op: str
    inputs: list[str]
    output: str


class Explanation(_M):
    rule_id: str
    rule_version: str
    verdict: Verdict
    conditional: bool
    reason_code: str
    facts: list[FactRef]
    edges: list[EdgeRef]
    derivation: list[Step]
    anchors: list[Anchor]
    depends_on_extracted: list[FactRef]
    weak: list[str]
    missing: list[str]
    notes: list[str]
    subject: dict[str, str] = {}
    suspects: list[str] = []


class Finding(_M):
    finding_id: str
    rule_id: str
    rule_version: str
    verdict: Verdict
    conditional: bool
    provenance: Literal["derived"] = "derived"
    reason_code: str
    explanation: Explanation
    snapshot_digest: str


class Report(_M):
    rule_id: str
    findings: list[Finding]
    stats: dict[str, int]
    snapshot_digest: str


class FactSource(Protocol):
    """Implemented by the GraphStore adapter."""

    def load(self, story: str) -> FactBase: ...
