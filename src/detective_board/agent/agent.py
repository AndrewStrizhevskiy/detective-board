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
from . import rule_first as rf
from .answer import CheckResult, citations_for, self_check, strip_reasoning
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
from .linking import Link, link_person
from .llm import LLM
from .memory import Turn, retrieval_query, summarize
from .retrieval_step import gate, hit_traces
from .router import Router, extract_names, parse_time_window
from .window import idf_from_jsonl

log = logging.getLogger(__name__)
_CODE = re.compile(r"[a-z_]{1,40}")


def _safe_code(code: str) -> str:
    """Error codes are a closed vocabulary; anything else must not reach the UI or prompt."""
    return code if _CODE.fullmatch(code) else "tool_error"


DECLINE_RETRY_PROBLEM = "model declined, retrying with a firmer instruction"
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
        self.idf = idf_from_jsonl(self.cfg.idf_chunks) if self.cfg.idf_chunks else None
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
        outcomes: list[rf.ToolOutcome] = []
        story: str | None = None
        person: str | None = None

        # 1. vector retrieval (always: it also supplies source text and the story)
        hits, rejected, gate_missing, support = yield from self._retrieve(
            sink, question, rq, cfg.top_k, 1
        )
        story = (hits or rejected or [None])[0].story if (hits or rejected) else None

        # 2. rule questions: names -> graph ids (R-12); ambiguity is reported, never guessed
        link: Link | None = None
        if decision.tools and self.graph is not None:
            stories = list(dict.fromkeys(h.story for h in (hits or rejected)))
            link = link_person(self.graph, names, stories)
            # ambiguous across stories none of which was retrieved: no story to scan
            no_story = link.status == "ambiguous" and link.story is None
            story = None if no_story else (link.story or story)
            person = link.person_id
            if link.status == "ambiguous":
                headers.append(f"ENTITY LINK: {link.note()}")

        # 3. graph
        if "graph" in decision.routes and self.graph is not None:
            res = yield from self._graph_step(sink, decision, names, story, link)
            if res is not None:
                graph_sources = ctx.sources_from_graph(res, cfg.max_graph_facts, 1)
                if res.nodes and link is None:  # rule questions take story/person from the link
                    story = story or res.nodes[0].story
                    person = next((n.id for n in res.nodes if n.kind == "person"), None)

        # 4. rule tools (timeline-alibi: MCP stdio or the same functions in-process)
        for tool in decision.tools:
            if self.tools is None:
                tool_errors.append(f"{tool}: no MCP client configured")
                outcomes.append(
                    rf.ToolOutcome(
                        tool, {"error": {"code": "skipped", "message": "no MCP client configured"}}
                    )
                )
                continue
            srcs, hdr, err, payload = yield from self._tool_step(
                sink, tool, question, story, person, link
            )
            outcomes.append(rf.ToolOutcome(tool, payload))
            tool_sources += srcs
            headers += hdr
            if err:
                tool_errors.append(f"{tool}: {err}")

        if cfg.rule_first and decision.tools:  # the answer is the rule result, not a model's text
            yield from self._rule_first_answer(
                sink, decision, question, story, link, hits, outcomes, headers
            )
            return
        # any other route that carried a rule result: an empty one must not read as agreement
        guard = bool(decision.tools) and not rf.has_rule_verdict(outcomes)

        def assemble(h: list[Any], gs: list[ctx.Source], ts: list[ctx.Source]) -> list[ctx.Source]:
            out = ctx.sources_from_hits(
                h, question, cfg.window_words, idf=self.idf, full_top1=cfg.strategy == "rank_full"
            )
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
        firm = False  # the previous attempt declined: same sources, firmer instruction
        for attempt in range(1, cfg.max_retries + 2):
            attempts = attempt
            if attempt > 1 and not firm:
                # one re-retrieve with more chunks; keep graph/tool facts
                if "vector" in decision.routes:
                    h2, r2, _, sup2 = yield from self._retrieve(
                        sink, question, rq, cfg.top_k + cfg.retry_extra_k, attempt
                    )
                    if h2:
                        hits, support = h2, sup2
                sources = assemble(hits, graph_sources, tool_sources)
            prompt = ctx.fit_prompt(
                question, sources, headers, memory, feedback, cfg.max_prompt_tokens, firm
            )
            msgs, nchars, sources = prompt.messages, prompt.chars, prompt.sources
            # graph/tool facts were renumbered with the sources; keep the lists in step
            graph_sources = [s for s in sources if s.origin == "graph"]
            tool_sources = [s for s in sources if s.origin == "tool"]
            yield sink.emit(
                EnrichedQuery(
                    attempt=attempt,
                    memory_chars=len(memory),
                    prompt_chars=nchars,
                    prompt_tokens_estimate=prompt.tokens,
                    max_prompt_tokens=cfg.max_prompt_tokens,
                    strategy=cfg.strategy,
                    window_words=cfg.window_words,
                    dropped_chunks=prompt.dropped,
                    sources=[
                        SourceTrace(
                            n=s.n,
                            chunk_id=s.chunk_id,
                            story=s.story,
                            char_start=s.char_start,
                            char_end=s.char_end,
                            origin=s.origin,
                            label=s.label,
                            window_start=s.win_start,
                            window_end=s.window_end,
                            window_char_start=s.char_start + s.win_start,
                            window_char_end=s.char_start + s.window_end,
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
            text = strip_reasoning("".join(parts))
            last = self_check(
                text,
                sources,
                cfg.min_quote_chars,
                cfg.min_claim_overlap,
                forbid_consistency=guard,
            )
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
                if cfg.decline_retry and not firm and attempt <= cfg.max_retries:
                    firm, feedback = True, ""
                    yield sink.emit(
                        CitationCheck(
                            attempt=attempt,
                            ok=False,
                            problems=[DECLINE_RETRY_PROBLEM],
                            action="retry",
                        )
                    )
                    continue
                break
            firm = False
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
            if support >= cfg.decline_fallback_min_support:
                done = yield from self._closest_passages(
                    sink, decision, question, sources, attempts
                )
                if done:
                    return
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
        if support >= cfg.decline_fallback_min_support and not guard:
            done = yield from self._closest_passages(sink, decision, question, sources, attempts)
            if done:
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
        return (found, [], missing, g.support) if g.passed else ([], found, missing, g.support)

    def _graph_step(
        self,
        sink: EventSink,
        decision: RouteDecided,
        names: list[str],
        story: str | None,
        link: Link | None = None,
    ):
        assert self.graph is not None
        meta: dict[str, Any] = {}
        if link is not None and link.status in ("ok", "ambiguous"):
            meta = {"linked_from": link.mention, "link": link.status}
        if link is not None and link.status == "ambiguous":
            kind = "find_entities"
            args: dict[str, Any] = {"name": link.matched, "kind": "person", "story": link.story}
        elif link is not None and link.person_id:
            if "check_alibi" in decision.tools:
                kind, args = "events_by_person", {"person": link.person_id, "story": link.story}
            else:  # the person's events and claims are one hop away (R-16b)
                kind, args = "neighbours", {"ref": link.person_id, "k": 1, "story": link.story}
        elif not names:
            return None
        elif "check_alibi" in decision.tools:
            kind, args = "events_by_person", {"person": names[0]}
        elif len(names) >= 2:
            kind, args = "shortest_path", {"a": names[0], "b": names[1]}
        else:
            kind, args = "neighbours", {"ref": names[0], "k": 1}
        step = "graph-1"
        yield sink.emit(GraphQuery(step_id=step, query_kind=kind, args=args | meta))
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

    def _skip(self, sink: EventSink, step: str, tool: str, code: str, why: str):
        yield sink.emit(
            ToolResult(
                step_id=step,
                server=self._server,
                tool=tool,
                ok=False,
                summary=f"skipped: {why}",
                error={"code": code, "message": why},
            )
        )
        return [], [], why, {"error": {"code": code, "message": why}}

    @property
    def _server(self) -> str:
        return getattr(self.tools, "server", "timeline-alibi")

    def _tool_step(
        self,
        sink: EventSink,
        tool: str,
        question: str,
        story: str | None,
        person: str | None,
        link: Link | None = None,
        attempt: int = 1,
    ):
        step = f"tool-{tool}" + (f"-{attempt}" if attempt > 1 else "")
        if story is None:
            return (
                yield from self._skip(sink, step, tool, "skipped", "no story could be determined")
            )
        args: dict[str, Any] = {"story": story}
        if tool == "check_alibi":
            win = parse_time_window(question)
            if link is not None and link.status == "ambiguous":
                return (yield from self._skip(sink, step, tool, "ambiguous", link.note()))
            if person is None or win is None:
                why = (
                    "no person found in the graph"
                    if person is None
                    else "no clock time in the question"
                )
                return (yield from self._skip(sink, step, tool, "skipped", why))
            args |= {"person_id": person, "window": win[0]}
        elif person:
            args["person_id"] = person
        yield sink.emit(
            ToolCall(
                step_id=step,
                server=self._server,
                tool=tool,
                arguments=args,
                timeout_s=self.cfg.tool_timeout_s,
            )
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
        if err:
            payload = {"error": err}
        srcs, hdr = ctx.sources_from_tool(tool, payload, self.cfg.max_tool_facts, 1)
        summary = (
            f"error {err['code']}" if err else f"status={payload.get('status')} items={len(srcs)}"
        )
        yield sink.emit(
            ToolResult(
                step_id=step,
                duration_ms=self._ms(t0),
                server=self._server,
                tool=tool,
                ok=not err,
                summary=summary,
                provenance=_tool_provenance(payload),
                explanation=_primary_explanation(payload),
                error=err or None,
            )
        )
        if err and err["code"] == "not_found" and "person_id" in args and tool != "check_alibi":
            if attempt == 1:  # the person has no events of their own (only claims): whole story
                srcs, hdr, e2, payload = yield from self._tool_step(
                    sink, tool, question, story, None, link, 2
                )
                note = (
                    f"SCOPE WIDENED: {args['person_id']} has no events of their own; the {tool} "
                    "results are for the whole story and may concern other people"
                )
                return srcs, [note, *hdr], e2, payload
        return srcs, hdr, (summary if err else None), payload

    def _rule_first_answer(
        self,
        sink: EventSink,
        decision: RouteDecided,
        question: str,
        story: str | None,
        link: Link | None,
        hits: list[Any],
        outcomes: list[rf.ToolOutcome],
        headers: list[str],
    ):
        """Deterministic answer for contradiction / alibi routes: a template over the tool result
        (docs/symbolic-layer.md). No model call; the same events as an LLM run, so the UI is
        unchanged: tokens stream from the template, the verbatim self-check runs on it."""
        cfg = self.cfg
        ans = rf.build_answer(
            question=question,
            story=story,
            outcomes=outcomes,
            link=link,
            notes=headers,
            hits=hits,
            coverage=rf.coverage_for(self.tools, self.graph, story),
            idf=self.idf,
            min_quote_chars=cfg.min_quote_chars,
        )
        sources = ans.sources
        yield sink.emit(
            EnrichedQuery(
                attempt=1,
                strategy=f"rule-first ({ans.kind}): no model call",
                sources=[
                    SourceTrace(
                        n=s.n,
                        chunk_id=s.chunk_id,
                        story=s.story,
                        char_start=s.char_start,
                        char_end=s.char_end,
                        origin=s.origin,
                        label=s.label,
                        window_start=s.win_start,
                        window_end=s.window_end,
                        window_char_start=s.char_start + s.win_start,
                        window_char_end=s.char_start + s.window_end,
                    )
                    for s in sources
                ],
                graph_facts=0,
                rule_facts=sum(1 for s in sources if s.origin == "tool"),
            )
        )
        for tok in re.findall(r"\S+\s*|\s+", ans.text):
            yield sink.emit(AnswerToken(attempt=1, text=tok))
        # the same verbatim check as for a model answer; sentences without a quote are statements
        # of the rule engine, the lexical-overlap test is for model paraphrase
        chk = self_check(ans.text, sources, cfg.min_quote_chars, 0.0, allow_uncited=True)
        if not chk.ok:  # cannot happen: every quote is copied from a source
            log.error("rule-first template failed its own check: %s", chk.problems)
            yield sink.emit(
                CitationCheck(attempt=1, ok=False, problems=chk.problems, action="refuse")
            )
            yield from self._refuse(
                sink, decision, "selfcheck_failed", ctx.REFUSAL_TEXT, chk.problems[:5], SEARCHED
            )
            return
        yield sink.emit(CitationCheck(attempt=1, ok=True, citations=chk.traces, action="accept"))
        cites, labels = citations_for(ans.text, sources)
        yield sink.emit(
            Final(
                status="answered",
                verified=True,
                answer=ans.text,
                citations=cites,
                provenance=labels,
                route=decision,
                attempts=1,
            )
        )

    def _closest_passages(
        self,
        sink: EventSink,
        decision: RouteDecided,
        question: str,
        sources: list[ctx.Source],
        attempts: int,
    ):
        """Deterministic fallback when the model declined or failed its check although the gate
        passed with high support: the best sentences of the shown excerpts, verbatim, nothing
        else. Returns False (nothing emitted) when no honest passage can be shown."""
        text = ctx.closest_passages(sources, question, self.idf)
        if text is None:
            return False
        chk = self_check(text, sources, self.cfg.min_quote_chars, 0.0, allow_uncited=True)
        if not chk.ok:  # cannot happen: every quote is copied from a shown window
            log.error("closest-passages template failed its own check: %s", chk.problems)
            return False
        for tok in re.findall(r"\S+\s*|\s+", text):
            yield sink.emit(AnswerToken(attempt=attempts + 1, text=tok))
        yield sink.emit(
            CitationCheck(attempt=attempts, ok=True, citations=chk.traces, action="partial")
        )
        cites, labels = citations_for(text, sources)
        yield sink.emit(
            Final(
                status="partial",
                verified=True,
                answer=text,
                citations=cites,
                provenance=labels,
                route=decision,
                attempts=attempts,
            )
        )
        return True

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
