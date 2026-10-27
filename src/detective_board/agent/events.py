"""Trace events (docs/data-schema.md section 5, adapted to the Phase 1 event list).

Type names differ from the doc draft (`route` -> `route_decided` ...); see the mapping in
`DOC_TYPE`. Every event has the envelope run_id/seq/ts; `EventSink` assigns seq and ts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from detective_board.symbolic.api import Explanation

Label = Literal["extracted", "derived", "conditional", "source_text"]
RouteName = Literal["vector", "graph", "mcp", "refusal"]

DOC_TYPE = {
    "query_translated": "translate (new)",
    "route_decided": "route",
    "retrieval_started": "retrieve.vector (start)",
    "retrieval_results": "retrieve.vector",
    "graph_query": "retrieve.graph (start)",
    "graph_results": "retrieve.graph",
    "tool_call": "tool.call",
    "tool_result": "tool.result",
    "enriched_query": "enrich",
    "answer_token": "answer (stream)",
    "citation_check": "selfcheck",
    "refusal": "refusal",
    "final": "answer + run.end",
}


def parse_explanation(obj: Any) -> Explanation | None:
    """A symbolic `Explanation` from a tool/graph payload, or None when absent or malformed.
    The object is validated, never rewritten: what the rule engine produced is what is shown."""
    if isinstance(obj, Explanation):
        return obj
    if not isinstance(obj, dict) or not obj:
        return None
    try:
        return Explanation.model_validate(obj)
    except ValidationError:
        return None


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = ""
    seq: int = 0
    ts: str = ""
    step_id: str | None = None
    duration_ms: int | None = None


class HitTrace(BaseModel):
    chunk_id: str
    story: str
    rank: int
    rrf: float
    ranks: dict[str, int] = {}
    scores: dict[str, float] = {}


class GateTrace(BaseModel):
    passed: bool
    best_score: float
    threshold: float
    support: float
    min_support: float
    reason: str


class SourceTrace(BaseModel):
    n: int
    chunk_id: str
    story: str
    char_start: int
    char_end: int
    origin: Literal["vector", "graph", "tool"]
    label: Label
    window_start: int | None = None  # shown excerpt, offsets in the chunk text
    window_end: int | None = None
    window_char_start: int | None = None  # the same excerpt in story offsets
    window_char_end: int | None = None


class CitationTrace(BaseModel):
    n: int
    verbatim: bool
    source_exists: bool


class Anchor(BaseModel):
    story: str
    chunk_id: str
    char_start: int
    char_end: int
    quote: str


class Citation(BaseModel):
    n: int
    quote: str
    anchor: Anchor
    label: Label


class ProvenanceLabel(BaseModel):
    n: int
    label: Label
    origin: Literal["vector", "graph", "tool"]
    confidence: str | None = None
    rule_id: str | None = None
    summary: str = ""
    explanation: Explanation | None = None  # rule-derived items only (docs/symbolic-layer.md 3.1)


class QueryTranslated(_Base):
    """A Cyrillic question was translated to English; everything after runs on `translated`."""

    type: Literal["query_translated"] = "query_translated"
    original: str
    translated: str | None = None  # None when the translation failed
    model: str
    ok: bool = True
    cached: bool = False
    error: str | None = None


class RouteDecided(_Base):
    type: Literal["route_decided"] = "route_decided"
    routes: list[RouteName]
    tools: list[str] = []
    method: Literal["rules", "llm"]
    reason: str
    matched: list[str] = []
    confidence: float | None = None


class RetrievalStarted(_Base):
    type: Literal["retrieval_started"] = "retrieval_started"
    query: str
    k: int
    attempt: int = 1


class RetrievalResults(_Base):
    type: Literal["retrieval_results"] = "retrieval_results"
    hits: list[HitTrace]
    gate: GateTrace
    chunk_ids: list[str]


class GraphQuery(_Base):
    type: Literal["graph_query"] = "graph_query"
    query_kind: str
    args: dict[str, Any] = {}


class GraphResults(_Base):
    type: Literal["graph_results"] = "graph_results"
    query_kind: str
    seeds: list[str] = []
    node_ids: list[str] = []
    edge_ids: list[int | str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    truncated: bool = False


class ToolCall(_Base):
    type: Literal["tool_call"] = "tool_call"
    server: str = "timeline-alibi"
    tool: str
    arguments: dict[str, Any]
    timeout_s: float


class ToolResult(_Base):
    type: Literal["tool_result"] = "tool_result"
    server: str = "timeline-alibi"
    tool: str
    ok: bool
    summary: str
    provenance: str | None = None  # derived | conditional | extracted, as the tool reported it
    explanation: Explanation | None = None  # the tool's own Explanation, unchanged
    error: dict[str, Any] | None = None


class EnrichedQuery(_Base):
    type: Literal["enriched_query"] = "enriched_query"
    attempt: int = 1
    sources: list[SourceTrace]
    graph_facts: int = 0
    rule_facts: int = 0
    memory_chars: int = 0
    prompt_chars: int = 0
    prompt_tokens_estimate: int = 0  # chars / 4
    max_prompt_tokens: int = 0
    strategy: str = ""  # rank_full | uniform: how excerpts were allocated
    window_words: int = 0
    dropped_chunks: list[str] = []  # chunk ids removed by the prompt budget, lowest rank first
    data_marked: bool = True  # corpus text is delimited and treated as data
    injection_suspects: list[int] = []  # source numbers whose text looks like instructions


class AnswerToken(_Base):
    type: Literal["answer_token"] = "answer_token"
    attempt: int = 1
    text: str


class CitationCheck(_Base):
    type: Literal["citation_check"] = "citation_check"
    attempt: int = 1
    ok: bool
    citations: list[CitationTrace] = []
    unsupported_claims: list[str] = []
    problems: list[str] = []
    action: Literal["accept", "retry", "partial", "refuse"]


class Refusal(_Base):
    type: Literal["refusal"] = "refusal"
    code: Literal[
        "out_of_scope", "no_evidence", "selfcheck_failed", "tool_error", "translation_failed"
    ]
    message: str
    missing: list[str] = []
    searched: list[str] = []


class Final(_Base):
    type: Literal["final"] = "final"
    status: Literal["answered", "partial", "refused"]
    verified: bool
    answer: str
    citations: list[Citation] = []
    provenance: list[ProvenanceLabel] = []
    route: RouteDecided | None = None
    attempts: int = 1
    refusal_code: str | None = None
    original_question: str | None = None  # set when the question was translated to English
    translated_question: str | None = None


TraceEvent = Annotated[
    QueryTranslated
    | RouteDecided
    | RetrievalStarted
    | RetrievalResults
    | GraphQuery
    | GraphResults
    | ToolCall
    | ToolResult
    | EnrichedQuery
    | AnswerToken
    | CitationCheck
    | Refusal
    | Final,
    Field(discriminator="type"),
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventSink:
    """Stamps events (run_id, seq, ts) and keeps them in emission order."""

    def __init__(self, run_id: str, now: Callable[[], datetime] = _utc_now) -> None:
        self.run_id = run_id
        self._now = now
        self.events: list[_Base] = []
        # Optional hook: called with the `final` event before it is stamped; may edit it and
        # return events (for example a last answer token) that are emitted ahead of it.
        self.on_final: Callable[[Final], list[_Base]] | None = None

    def emit(self, ev: _Base) -> _Base:
        if isinstance(ev, Final) and self.on_final is not None:
            for extra in self.on_final(ev):
                self._stamp(extra)
        return self._stamp(ev)

    def _stamp(self, ev: _Base) -> _Base:
        ev.run_id = self.run_id
        ev.seq = len(self.events)
        ev.ts = self._now().astimezone(UTC).isoformat(timespec="milliseconds")
        self.events.append(ev)
        return ev
