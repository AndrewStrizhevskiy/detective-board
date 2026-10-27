"""Graph + rules route end to end on a hand-built graph: router -> linking -> graph step ->
in-process timeline-alibi tools (same functions as the MCP server) -> trace and answer labels."""

import re

import pytest

from detective_board.agent import AgentConfig, FakeLLM
from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.extract import normalise
from detective_board.extract.schema_v2 import Claim, Entity, Event, Extraction
from detective_board.graph import ChunkRef, GraphStore, SqliteFactSource
from detective_board.mcp import tools as mcp_tools

from .conftest import FakeRetriever, hit, make_agent, types

S = "wl"
T1 = "Some time later Garcia looked in at my door at Wisteria Lodge. It was nearly one o'clock."
T2 = "He had been there on Oxshott Common since one o'clock, said Baynes of Garcia."
T3 = "Lucas Moreno and Ana Moreno, his cousin, were at Wisteria Lodge."


def _graph(*, cousins: bool = False, baynes: bool = False) -> GraphStore:
    g = GraphStore()
    rows = [(1, T1), (2, T2)] + ([(3, T3)] if cousins else [])
    refs = {n: ChunkRef(f"{S}-{n:04d}", S, 1000 * n, 1000 * n + len(t), t) for n, t in rows}
    person = lambda name, q, *al: Entity(name=name, type="person", aliases=list(al), quote=q)  # noqa: E731
    place = lambda name, q: Entity(name=name, type="place", quote=q)  # noqa: E731
    items = [
        (
            refs[1],
            Extraction(
                entities=[person("Garcia", "Garcia"), place("Wisteria Lodge", "Wisteria Lodge")],
                events=[
                    Event(
                        description="Garcia looks in at the door",
                        time_text="nearly one o'clock",
                        place="Wisteria Lodge",
                        participants=["Garcia"],
                        quote="Some time later Garcia looked in at my door",
                    )
                ],
            ),
        ),
        (
            refs[2],
            Extraction(
                entities=[place("Oxshott Common", "Oxshott Common")],
                events=[
                    Event(
                        description="Garcia lies dead on Oxshott Common",
                        time_text="since one o'clock",
                        place="Oxshott Common",
                        participants=["Garcia"],
                        quote="He had been there on Oxshott Common since one o'clock",
                    )
                ],
                claims=[
                    Claim(
                        speaker="Baynes",
                        content="Garcia lay on the Common since one o'clock",
                        quote="said Baynes of Garcia",
                    )
                ]
                if baynes
                else [],
            ),
        ),
    ]
    if cousins:
        items.append(
            (
                refs[3],
                Extraction(
                    entities=[
                        person("Lucas Moreno", "Lucas Moreno", "Moreno"),
                        person("Ana Moreno", "Ana Moreno", "Moreno"),
                    ]
                ),
            )
        )
    g.ingest_many(items)
    for eid in (f"e:{S}-0001:0", f"e:{S}-0002:0"):
        g.set_event_day(eid, 1, confidence="low")
    normalise.apply(g, S)
    return g


_TOOL = re.compile(r"n=(\d+) [^>\n]*origin=tool[^>\n]*>>>\n(.*?)\n<<<END", re.S)


def _answer(messages):
    found = _TOOL.findall(messages[-1]["content"])
    if not found:
        return "In these materials there is nothing about this."
    cites = " ".join(f'[{n}: "{text}"]' for n, text in found)
    return f"If these facts are right, Garcia was at two places at one o'clock. {cites}"


QUESTION = "Is there a conflict about where Garcia was at one o'clock?"


def _run(g, question=QUESTION, llm=None):
    """The LLM path (`rule_first=False`): these tests pin the prompt and the trace; the
    rule-first path has its own tests in test_rule_first.py."""
    llm = llm or FakeLLM(_answer)
    retr = FakeRetriever([hit(1, T1, story=S), hit(2, T2, story=S)])
    cfg = AgentConfig(answer_mode="generate", rule_first=False)
    agent = make_agent(llm, retr, graph=g, tools=InProcessRulesClient(g), config=cfg)
    return list(agent.ask(question)), llm


def test_contradiction_question_goes_through_graph_and_rules():
    ev, llm = _run(_graph())
    t = types(ev)
    assert t.index("retrieval_results") < t.index("graph_query") < t.index("graph_results")
    assert t.index("graph_results") < t.index("tool_call") < t.index("tool_result")
    route = ev[0]
    assert route.routes == ["mcp", "graph", "vector"] and "rules R1-R3" in route.reason
    gq = next(e for e in ev if e.type == "graph_query")
    assert gq.args["ref"] == f"p:{S}:garcia" and gq.args["link"] == "ok"
    gr = next(e for e in ev if e.type == "graph_results")
    assert {n["kind"] for n in gr.nodes} == {"person", "event"}
    call = next(e for e in ev if e.type == "tool_call")
    assert call.server == "timeline-alibi[in-process]"
    assert call.arguments == {"story": S, "person_id": f"p:{S}:garcia"}
    res = next(e for e in ev if e.type == "tool_result")
    assert res.ok and res.provenance == "conditional"
    exp = res.explanation
    assert (exp.rule_id, exp.verdict.value, exp.conditional) == ("R1", "violated", True)
    assert exp.reason_code == "OVERLAP_DIFFERENT_PLACES"
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    tool_labels = [p for p in fin.provenance if p.origin == "tool"]
    assert tool_labels and all(p.label == "conditional" for p in tool_labels)
    assert all(p.explanation is not None and p.rule_id == "R1" for p in tool_labels)
    assert {c.quote for c in fin.citations if c.label == "conditional"} == {
        "Some time later Garcia looked in at my door",
        "He had been there on Oxshott Common since one o'clock",
    }
    assert "RULE RESULT find_contradictions: 1 violated finding(s)" in llm.calls[0][1]["content"]


def test_in_process_tools_equal_the_mcp_tool_functions():
    g = _graph()
    args = {"story": S, "person_id": f"p:{S}:garcia"}
    direct = mcp_tools.find_contradictions(SqliteFactSource(g), **args)
    assert InProcessRulesClient(g).call("find_contradictions", args, timeout=1) == direct
    bad = InProcessRulesClient(g).call("check_alibi", {"story": S}, timeout=1)
    assert bad["error"]["code"] == "invalid_input"
    assert InProcessRulesClient(g).call("rm", {}, timeout=1)["error"]["code"] == "not_found"


def test_run_is_deterministic():
    a, _ = _run(_graph())
    b, _ = _run(_graph())
    assert [e.model_dump_json() for e in a] == [e.model_dump_json() for e in b]


def test_ambiguous_name_is_reported_not_guessed():
    g = _graph(cousins=True)
    ev, llm = _run(g, "Is there a conflict about where Moreno was at one o'clock?")
    gq = next(e for e in ev if e.type == "graph_query")
    assert gq.query_kind == "find_entities" and gq.args["link"] == "ambiguous"
    call = next(e for e in ev if e.type == "tool_call")
    assert "person_id" not in call.arguments  # story-wide scan, no chosen person
    prompt = llm.calls[0][1]["content"]
    assert "ENTITY LINK: name 'Moreno' is ambiguous" in prompt
    assert "Ana Moreno" in prompt and "Lucas Moreno" in prompt


def test_ambiguous_alibi_is_skipped_with_the_candidates():
    g = _graph(cousins=True)
    ev, _ = _run(g, "Where was Moreno at one o'clock? Check the alibi.")
    res = next(e for e in ev if e.type == "tool_result" and e.tool == "check_alibi")
    assert not res.ok and res.error["code"] == "ambiguous"
    assert "Ana Moreno" in res.error["message"]
    assert "tool_call" not in [e.type for e in ev if getattr(e, "tool", "") == "check_alibi"]


def test_person_known_only_through_claims_is_scanned_without_widening():
    # R-19: a speaker with no events is a known person; the first call answers, no retry
    ev, llm = _run(_graph(baynes=True), "Is there a conflict in what Baynes said?")
    results = [e for e in ev if e.type == "tool_result"]
    assert [r.step_id for r in results] == ["tool-find_contradictions"] and results[0].ok
    calls = [e.arguments for e in ev if e.type == "tool_call"]
    assert calls == [{"story": S, "person_id": f"p:{S}:baynes"}]
    assert "SCOPE WIDENED" not in llm.calls[0][1]["content"]


def test_ambiguous_across_unretrieved_stories_runs_no_tool():
    g = _graph(cousins=True)
    retr = FakeRetriever([hit(1, T1, story="other"), hit(2, T2, story="other")])
    for sid in ("x", "y"):
        text = "Pablo Ruiz lived there."
        g.ingest(
            ChunkRef(f"{sid}-0001", sid, 0, len(text), text),
            Extraction(entities=[Entity(name="Pablo Ruiz", type="person", quote="Pablo Ruiz")]),
        )
    agent = make_agent(FakeLLM(_answer), retr, graph=g, tools=InProcessRulesClient(g))
    ev = list(agent.ask("Is there a conflict about Pablo Ruiz?"))
    assert "tool_call" not in types(ev)
    res = next(e for e in ev if e.type == "tool_result")
    assert res.error["code"] == "skipped"


@pytest.mark.parametrize("question", ["Where was Garcia at one o'clock? Check his alibi."])
def test_alibi_with_linked_person_calls_check_alibi(question):
    ev, _ = _run(_graph(), question)
    call = next(e for e in ev if e.type == "tool_call" and e.tool == "check_alibi")
    assert call.arguments["person_id"] == f"p:{S}:garcia"
    gq = next(e for e in ev if e.type == "graph_query")
    assert gq.query_kind == "events_by_person" and gq.args["person"] == f"p:{S}:garcia"
