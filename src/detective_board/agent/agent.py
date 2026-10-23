"""Agent.ask(question, history) -> iterator of trace events ending with `final`."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from detective_board.symbolic.api import Explanation

from . import context as ctx
from .answer import CheckResult, citations_for, self_check
from .backends import GraphBackend, Retriever, ToolClient
from .config import AgentConfig
from .events import (
    AnswerToken,
    CitationCheck,
    EnrichedQuery,
    EventSink,
    Final,
    GraphQuery,
    GraphResults,
    Refusal,
    RetrievalResults,
    RetrievalStarted,
    RouteDecided,
    SourceTrace,
    ToolCall,
    ToolResult,
    TraceEvent,
    _Base,
    _utc_now,
    parse_explanation,
)
from .llm import LLM
from .memory import Turn, retrieval_query, summarize
from .retrieval_step import gate, hit_traces
from .router import Router, extract_names, parse_time_window

log = logging.getLogger(__name__)
_CODE = re.compile(r"[a-z_]{1,40}")


def _safe_code(code: str) -> str:
    """Error codes are a closed vocabulary; anything else must not reach the UI or prompt."""
    return code if _CODE.fullmatch(code) else "tool_error"


SEARCHED = ["hybrid retrieval (BM25 + vector) over the Holmes corpus"]


class Agent:
    def __init__(
        self,
        llm: LLM,
        retriever: Retriever,
        graph: GraphBackend | None = None,
        tools: ToolClient | None = None,
        config: AgentConfig | None = None,
        *,
        router_llm: LLM | None = None,
        now: Callable[[], datetime] = _utc_now,
        mono: Callable[[], float] = time.monotonic,
        run_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self.llm, self.retriever, self.graph, self.tools = llm, retriever, graph, tools
        self.cfg = config or AgentConfig()
        self.router = Router(router_llm or llm, self.cfg.use_llm_router)
        self._now, self._mono, self._run_id = now, mono, run_id

    # ------------------------------------------------------------------ public
    def ask(self, question: str, history: Sequence[Turn] = ()) -> Iterator[TraceEvent]:
        sink = EventSink(self._run_id(), self._now)
        yield from self._run(sink, question, list(history))  # type: ignore[misc]

    # ------------------------------------------------------------------ pipeline
    def _ms(self, t0: float) -> int:
        return int((self._mono() - t0) * 1000)

    def _run(self, sink: EventSink, question: str, history: list[Turn]) -> Iterator[_Base]:
        cfg = self.cfg
        decision = self.router.decide(question)
        yield sink.emit(decision)
        if decision.routes == ["refusal"]:
            yield from self._refuse(sink, decision, "out_of_scope", ctx.REFUSAL_TEXT, [], [])
            return

        rq = retrieval_query(question, history)
        names = extract_names(question)
        hits: list[Any] = []
        rejected: list[Any] = []
        gate_missing: list[str] = []
        sources: list[ctx.Source] = []
        headers: list[str] = []
        graph_sources: list[ctx.Source] = []
        tool_sources: list[ctx.Source] = []
        tool_errors: list[str] = []
        story: str | None = None
        person: str | None = None

        # 1. vector retrieval (always: it also supplies source text and the story)
        hits, rejected, gate_missing = yield from self._retrieve(sink, question, rq, cfg.top_k, 1)
        story = (hits or rejected or [None])[0].story if (hits or rejected) else None

        # 2. graph
        if "graph" in decision.routes and self.graph is not None:
            res = yield from self._graph_step(sink, decision, names, story)
            if res is not None:
                graph_sources = ctx.sources_from_graph(res, cfg.max_graph_facts, 1)
                if res.nodes:
                    story = story or res.nodes[0].story
                    person = next((n.id for n in res.nodes if n.kind == "person"), None)

        # 3. MCP tools
        for tool in decision.tools:
            if self.tools is None:
                tool_errors.append(f"{tool}: no MCP client configured")
                continue
            srcs, hdr, err = yield from self._tool_step(sink, tool, question, names, story, person)
            tool_sources += srcs
            headers += hdr
            if err:
                tool_errors.append(f"{tool}: {err}")

        def assemble(h: list[Any], gs: list[ctx.Source], ts: list[ctx.Source]) -> list[ctx.Source]:
            out = ctx.sources_from_hits(h)
            n = len(out) + 1
            out += [_renum(s, n + i) for i, s in enumerate(gs)]
            n = len(out) + 1
            out += [_renum(s, n + i) for i, s in enumerate(ts)]
            return out

        sources = assemble(hits, graph_sources, tool_sources)
        if not sources:
            if tool_errors and not rejected:
                yield from self._refuse(
                    sink,
                    decision,
                    "tool_error",
                    "The tool call failed and no other evidence was found: "
                    + "; ".join(tool_errors),
                    tool_errors,
                    SEARCHED,
                )
            else:
                yield from self._refuse(
                    sink, decision, "no_evidence", ctx.REFUSAL_TEXT, gate_missing, SEARCHED
                )
            return

        memory = summarize(history, cfg.memory_turns, cfg.memory_max_chars)
        feedback = ""
        last: CheckResult | None = None
        text = ""
        attempts = 0
        for attempt in range(1, cfg.max_retries + 2):
            attempts = attempt
            if attempt > 1:
                # one re-retrieve with more chunks; keep graph/tool facts
                if "vector" in decision.routes:
                    h2, r2, _ = yield from self._retrieve(
                        sink, question, rq, cfg.top_k + cfg.retry_extra_k, attempt
                    )
                    if h2:
                        hits = h2
                sources = assemble(hits, graph_sources, tool_sources)
            msgs, nchars = ctx.build_messages(question, sources, headers, memory, feedback)
            yield sink.emit(
                EnrichedQuery(
                    attempt=attempt,
                    memory_chars=len(memory),
                    prompt_chars=nchars,
                    sources=[
                        SourceTrace(
                            n=s.n,
                            chunk_id=s.chunk_id,
                            story=s.story,
                            char_start=s.char_start,
                            char_end=s.char_end,
                            origin=s.origin,
                            label=s.label,
                        )
                        for s in sources
                    ],
                    graph_facts=len(graph_sources),
                    rule_facts=len(tool_sources),
                    injection_suspects=[s.n for s in sources if s.suspect],
                )
            )
            parts: list[str] = []
            for tok in self.llm.chat(msgs, temperature=cfg.temperature, seed=cfg.seed):
                parts.append(tok)
                yield sink.emit(AnswerToken(attempt=attempt, text=tok))
            text = "".join(parts).strip()
            last = self_check(text, sources, cfg.min_quote_chars, cfg.min_claim_overlap)
            if last.ok:
                yield sink.emit(
                    CitationCheck(attempt=attempt, ok=True, citations=last.traces, action="accept")
                )
                cites, labels = citations_for(text, sources)
                yield sink.emit(
                    Final(
                        status="answered",
                        verified=True,
                        answer=text,
                        citations=cites,
                        provenance=labels,
                        route=decision,
                        attempts=attempt,
                    )
                )
                return
            if last.refusal_like:
                break
            more = attempt <= cfg.max_retries
            action = "retry" if more else ("partial" if last.has_verified else "refuse")
            yield sink.emit(
                CitationCheck(
                    attempt=attempt,
                    ok=False,
                    citations=last.traces,
                    unsupported_claims=last.unsupported,
                    problems=last.problems,
                    action=action,
                )
            )
            feedback = "; ".join(last.problems[:5])

        assert last is not None
        if last.refusal_like:
            yield sink.emit(
                CitationCheck(attempt=attempts, ok=False, problems=last.problems, action="refuse")
            )
            yield from self._refuse(
                sink, decision, "no_evidence", ctx.REFUSAL_TEXT, gate_missing, SEARCHED
            )
            return
        if last.has_verified:
            cites, labels = citations_for(last.partial_text, sources)
            msg = (
                last.partial_text
                + "\n\n[UNVERIFIED: parts of the draft answer were removed because "
                "their quotes could not be verified in the sources.]"
            )
            yield sink.emit(
                Final(
                    status="partial",
                    verified=False,
                    answer=msg,
                    citations=cites,
                    provenance=labels,
                    route=decision,
                    attempts=attempts,
                )
            )
            return
        yield from self._refuse(
            sink,
            decision,
            "selfcheck_failed",
            "The draft answer could not be verified against the sources. " + ctx.REFUSAL_TEXT,
            last.problems[:5],
            SEARCHED,
            attempts=attempts,
        )

    # ------------------------------------------------------------------ steps
    def _retrieve(self, sink: EventSink, question: str, rq: str, k: int, attempt: int):
        step = f"retrieval-{attempt}"
        yield sink.emit(RetrievalStarted(step_id=step, query=rq, k=k, attempt=attempt))
        t0 = self._mono()
        found = self.retriever.search(rq, k)
        g, missing = gate(question, found, self.cfg)
        yield sink.emit(
            RetrievalResults(
                step_id=step,
                duration_ms=self._ms(t0),
                hits=hit_traces(found),
                gate=g,
                chunk_ids=[h.chunk_id for h in found],
            )
        )
        return (found, [], missing) if g.passed else ([], found, missing)

    def _graph_step(
        self, sink: EventSink, decision: RouteDecided, names: list[str], story: str | None
    ):
        assert self.graph is not None
        if not names:
            return None
        if "check_alibi" in decision.tools:
            kind, args = "events_by_person", {"person": names[0]}
        elif len(names) >= 2:
            kind, args = "shortest_path", {"a": names[0], "b": names[1]}
        else:
            kind, args = "neighbours", {"ref": names[0], "k": 1}
        step = "graph-1"
        yield sink.emit(GraphQuery(step_id=step, query_kind=kind, args=args))
        t0 = self._mono()
        try:
            res = getattr(self.graph, kind)(**args)
        except Exception as e:  # backend failure must not kill the run
            yield sink.emit(
                GraphResults(
                    step_id=step,
                    duration_ms=self._ms(t0),
                    query_kind=kind,
                    seeds=[f"error: {type(e).__name__}"],
                )
            )
            return None
        p = res.trace_payload()
        _mark_derived_edges(p["edges"], res.edges)
        yield sink.emit(
            GraphResults(
                step_id=step,
                duration_ms=self._ms(t0),
                query_kind=kind,
                seeds=p["seeds"],
                node_ids=res.node_ids,
                edge_ids=res.edge_ids,
                nodes=p["nodes"],
                edges=p["edges"],
                truncated=p["truncated"],
            )
        )
        return res

    def _tool_step(
        self,
        sink: EventSink,
        tool: str,
        question: str,
        names: list[str],
        story: str | None,
        person: str | None,
    ):
        step = f"tool-{tool}"
        if story is None:
            yield sink.emit(
                ToolResult(
                    step_id=step,
                    tool=tool,
                    ok=False,
                    summary="skipped: story unknown",
                    error={"code": "skipped", "message": "no story could be determined"},
                )
            )
            return [], [], "no story could be determined"
        args: dict[str, Any] = {"story": story}
        if tool == "check_alibi":
            win = parse_time_window(question)
            if person is None or win is None:
                why = (
                    "no person found in the graph"
                    if person is None
                    else "no clock time in the question"
                )
                yield sink.emit(
                    ToolResult(
                        step_id=step,
                        tool=tool,
                        ok=False,
                        summary=f"skipped: {why}",
                        error={"code": "skipped", "message": why},
                    )
                )
                return [], [], why
            args |= {"person_id": person, "window": win[0]}
        elif person:
            args["person_id"] = person
        yield sink.emit(
            ToolCall(step_id=step, tool=tool, arguments=args, timeout_s=self.cfg.tool_timeout_s)
        )
        t0 = self._mono()
        payload: dict[str, Any]
        try:
            payload = self.tools.call(tool, args, timeout=self.cfg.tool_timeout_s)  # type: ignore[union-attr]
        except Exception as e:
            log.warning("tool %s failed: %s: %s", tool, type(e).__name__, e)
            payload = {"error": {"code": "internal", "message": "internal tool error"}}
        err = payload.get("error")
        if err and not (isinstance(err, dict) and isinstance(err.get("code"), str)):
            log.warning("tool %s returned malformed error: %.200r", tool, err)
            err = {"code": "tool_error", "message": "tool call failed"}
        elif isinstance(err, dict):
            err = {"code": _safe_code(err["code"]), "message": "tool call failed"}
        srcs, hdr = ctx.sources_from_tool(tool, payload, self.cfg.max_tool_facts, 1)
        summary = (
            f"error {err['code']}" if err else f"status={payload.get('status')} items={len(srcs)}"
        )
        yield sink.emit(
            ToolResult(
                step_id=step,
                duration_ms=self._ms(t0),
                tool=tool,
                ok=not err,
                summary=summary,
                provenance=_tool_provenance(payload),
                explanation=_primary_explanation(payload),
                error=err or None,
            )
        )
        return srcs, hdr, (summary if err else None)

    def _refuse(
        self,
        sink: EventSink,
        decision: RouteDecided,
        code: str,
        message: str,
        missing: list[str],
        searched: list[str],
        attempts: int = 1,
    ):
        yield sink.emit(Refusal(code=code, message=message, missing=missing, searched=searched))  # type: ignore[arg-type]
        yield sink.emit(
            Final(
                status="refused",
                verified=True,
                answer=message,
                route=decision,
                attempts=attempts,
                refusal_code=code,
            )
        )


def _tool_provenance(payload: dict[str, Any]) -> str | None:
    """The tool's label: top-level, else that of the first rule item (find_contradictions)."""
    if payload.get("provenance"):
        return payload["provenance"]
    for key in ("findings", "overlaps"):
        for it in payload.get(key) or []:
            if isinstance(it, dict) and it.get("provenance"):
                return it["provenance"]
    return None


def _primary_explanation(payload: dict[str, Any]) -> Explanation | None:
    """The tool's own Explanation, unchanged: the top-level one (check_alibi), else the first
    rule-derived item's. Every item's explanation also travels with its source in `final`."""
    exp = parse_explanation(payload.get("explanation"))
    if exp is not None:
        return exp
    for key in ("findings", "overlaps"):
        for it in payload.get(key) or []:
            exp = parse_explanation(it.get("explanation")) if isinstance(it, dict) else None
            if exp is not None:
                return exp
    return None


def _mark_derived_edges(rows: list[dict[str, Any]], hits: list[Any]) -> None:
    """Rule-derived graph edges carry `provenance` and, when stored, their `explanation`."""
    by_id = {e.id: e for e in hits}
    for row in rows:
        e = by_id.get(row["id"])
        if e is None or e.provenance != "derived":
            continue
        row["provenance"] = "derived"
        exp = parse_explanation(e.props.get("explanation"))
        if exp is not None:
            row["explanation"] = exp.model_dump(mode="json")


def _renum(s: ctx.Source, n: int) -> ctx.Source:
    return replace(s, n=n)
