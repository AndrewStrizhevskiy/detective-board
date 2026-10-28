"""Alibi / presence table: router, template (hand-built payloads) and agent level (no Ollama)."""

import json
from pathlib import Path

import pytest

from detective_board.agent import AgentConfig, FakeLLM
from detective_board.agent.answer import CITATION
from detective_board.agent.honesty import asserts_consistency
from detective_board.agent.linking import Link
from detective_board.agent.presence_answer import NO_CONFLICT, build_presence_answer
from detective_board.agent.router import Router
from detective_board.agent.rule_first import ToolOutcome
from detective_board.agent.rules_client import InProcessRulesClient

from .conftest import FakeRetriever, FakeTools, hit, make_agent
from .test_graph_route import T1, T2, S, _graph

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden"


# ---- router ---------------------------------------------------------------
@pytest.mark.parametrize(
    "q",
    [
        "Where was Aloysius Garcia that night according to the testimonies?",
        "Who says where Lady Brackenstall was?",
        "Alibi table for James McCarthy",
        "Where did Eccles say Garcia was?",
        "Where was Sherlock Holmes in Silver Blaze?",
        "What was the alibi of Mr. Windibank?",
        "Whereabouts of Dr. Roylott according to the witnesses' testimony",
    ],
)
def test_router_presence_table_positive(q):
    d = Router().decide(q)
    assert d.tools == ["presence_table"] and d.routes == ["mcp", "graph", "vector"], q


@pytest.mark.parametrize(
    "q,tools",
    [
        # a clock time keeps check_alibi
        ("Where was Aloysius Garcia at one o'clock?", ["check_alibi"]),
        ("What was Mr. Windibank's alibi at 9 p.m.?", ["check_alibi"]),
        ("Who says where Garcia was at nine o'clock?", []),  # as before: no alibi wording
        ("Is Holmes's alibi for nine o'clock sound?", ["check_alibi"]),
        # a time question is not a presence question
        ("At what time was William Kirwan shot?", ["check_alibi"]),
        # contradiction wording wins
        ("Is there a conflict about where Garcia was?", ["find_contradictions"]),
        (
            "Do the testimonies contradict each other about where Garcia was?",
            ["find_contradictions"],
        ),
        # timeline wording wins
        (
            "Give the timeline of the night Garcia died, according to the testimonies",
            ["build_timeline"],
        ),
        # no whereabouts wording: not stolen from the text path
        ("According to Watson, what did Holmes eat?", []),
        ("What did the testimonies say about the knife?", []),
        ("According to McFarlane's own statement, where did he spend the night?", []),
        ("Who says the snake was a swamp adder?", []),
    ],
)
def test_router_presence_table_non_matches(q, tools):
    d = Router().decide(q)
    assert "presence_table" not in d.tools and d.tools == tools, q


def test_router_golden_sets_only_two_intended_changes():
    """Sets: questions.jsonl (64) and contradictions.jsonl (43). Before this feature every
    alibi-pattern question without a clock time was routed to check_alibi (skipped by the agent);
    only the two 'Where was X when ...' contradiction questions switch to the table."""
    r = Router()
    changed = {}
    for name in ("questions", "contradictions"):
        for line in (GOLDEN / f"{name}.jsonl").read_text().splitlines():
            d = json.loads(line)
            dec = r.decide(d["question"])
            if "presence_table" in dec.tools:
                changed[d["id"]] = dec.tools
    assert changed == {"c002": ["presence_table"], "c004": ["presence_table"]}


# ---- template -------------------------------------------------------------
def anchor(quote, start, chunk="wl-0001"):
    return {
        "story": S,
        "chunk_id": chunk,
        "char_start": start,
        "char_end": start + len(quote),
        "quote": quote,
    }


def row(rid, place, quote, start, **kw):
    r = {
        "row_id": rid,
        "kind": "event",
        "polarity": "affirm",
        "place_id": None,
        "place": place,
        "when": None,
        "time_text": None,
        "narrator": True,
        "speaker_id": None,
        "confidence": "high",
        "anchors": [anchor(quote, start)],
    }
    return r | kw


def payload(rows, **kw):
    p = {
        "status": "ok",
        "person_id": "p:wl:garcia",
        "rows": rows,
        "total_rows": len(rows),
        "events_without_place": 0,
        "truncated": False,
        "conflicts": [],
        "provenance": "derived",
        "rule_id": "R1",
    }
    return p | kw


def render(p, link=None, names=None):
    out = [ToolOutcome("presence_table", p)]
    return build_presence_answer(story=S, outcomes=out, link=link, names=names or {})


def prose(text):
    return CITATION.sub("", text)


NAMES = {"p:wl:garcia": "Aloysius Garcia", "p:wl:eccles": "Scott Eccles"}


def test_rows_with_and_without_slots():
    rows = [
        row(
            "e1",
            "Wisteria Lodge",
            "Garcia looked in at my door",
            10,
            time_text="nearly one o'clock",
            narrator=False,
            speaker_id="p:wl:eccles",
            curated=True,
        ),
        row("e2", "Oxshott Common", "dead on Oxshott Common", 90, narrator=False),
        row("e3", "the garden", "walked in the garden", 200, confidence="low"),
    ]
    ans = render(payload(rows), names=NAMES)
    lines = ans.text.splitlines()
    assert ans.kind == "presence"
    assert lines[0].startswith(
        "Presence table for Aloysius Garcia in wl: the graph holds 3 places for this person; "
        "3 are shown."
    )
    assert lines[1].startswith(
        "1. When: nearly one o'clock. Where: Wisteria Lodge. Who says so: Scott Eccles. "
        'Source: curated [1: "Garcia looked in at my door"]'
    )
    assert (
        "2. When: time not stated. Where: Oxshott Common. Who says so: speaker not stated."
        in ans.text
    )
    assert "3. When: time not stated. Where: the garden. Who says so: the narrator. " in ans.text
    assert "Source: extracted, low confidence" in ans.text
    assert NO_CONFLICT in ans.text and "Verdict (rule R1):" in ans.text
    assert not asserts_consistency(prose(ans.text))
    assert len(ans.sources) == 3


def test_denial_row_and_stated_date():
    d = row(
        "c1",
        "Oxshott Common",
        "I was never on the Common",
        300,
        kind="claim",
        polarity="deny",
        narrator=False,
        speaker_id="p:wl:garcia",
    )
    dated = row(
        "e1",
        "Wisteria Lodge",
        "Garcia looked in at my door",
        10,
        when={"story_day": 738_000, "start_min": 780, "end_min": 780, "confidence": "high"},
    )
    ans = render(payload([d, dated]), names=NAMES)
    assert ans.text.index("Where: Wisteria Lodge") < ans.text.index("not at Oxshott Common")
    assert "Where: not at Oxshott Common. Who says so: Aloysius Garcia denies." in ans.text
    assert "(date in the text), 13:00" in ans.text


def test_conflict_between_rows_uses_the_findings_own_label():
    rows = [
        row("e1", "the oaken chair", "tied to the chair", 10),
        row("e2", "the window", "standing at the window", 90),
    ]
    conf = {
        "rule": "R1",
        "reason_code": "OVERLAP_DIFFERENT_PLACES",
        "provenance": "conditional",
        "row_ids": ["e2", "e1"],
        "explanation": None,
    }
    ans = render(payload(rows, conflicts=[conf]), names=NAMES)
    assert (
        "- Conflict between row 1 and row 2: R1 verdict violated (OVERLAP_DIFFERENT_PLACES), "
        "label conditional." in ans.text
    )
    assert "Conditional because these inputs are low-confidence" in ans.text
    assert NO_CONFLICT not in ans.text
    derived = render(payload(rows, conflicts=[conf | {"provenance": "derived"}]))
    assert "label derived." in derived.text and "Derived: none of the extracted" in derived.text


def test_conflict_with_a_row_not_listed_and_truncation():
    rows = [row("e1", "A", "quote one here", 10)]
    conf = {"rule": "R1", "reason_code": "X", "provenance": "derived", "row_ids": ["e1", "e99"]}
    ans = render(payload(rows, total_rows=20, truncated=True, conflicts=[conf]))
    assert "holds 20 places for this person; 1 is shown, the rest were cut off." in ans.text
    assert "Conflict between row 1 and a row that is not listed" in ans.text


def test_empty_error_and_unknown_person():
    empty = render(payload([], status="insufficient_evidence", events_without_place=2))
    assert empty.kind == "empty" and "holds no place" in empty.text
    assert "2 event(s) of this person have no place" in empty.text
    err = render({"error": {"code": "timeout", "message": "x"}})
    assert err.kind == "failed" and "could be built" in err.text and "(timeout)" in err.text
    link = Link("not_found", None, reason="no person in the graph named Zed Nobody")
    miss = render({"error": {"code": "skipped", "message": "no person found"}}, link=link)
    assert "no person in the graph named Zed Nobody" in miss.text and "1." not in miss.text
    for a in (empty, err, miss):
        assert not asserts_consistency(prose(a.text))


def test_row_without_citable_quote_and_markup_in_fields():
    r = row("e1", "the [dark] room", "x", 5)  # too short to cite
    ans = render(payload([r]))
    assert "(no citable quote)" in ans.text and "the (dark) room" in ans.text


# ---- agent level ----------------------------------------------------------
def run(question, graph=None, tools=None, payload_=None, hits=None):
    llm = FakeLLM("MODEL TEXT MUST NOT APPEAR")
    retr = FakeRetriever(hits or [hit(1, T1, story=S), hit(2, T2, story=S)])
    if tools is None:
        tools = InProcessRulesClient(graph) if payload_ is None else FakeTools(payload_)
    cfg = AgentConfig(answer_mode="extractive")
    agent = make_agent(llm, retr, graph=graph, tools=tools, config=cfg)
    return list(agent.ask(question)), llm, tools


def test_agent_builds_the_table_from_the_graph_without_a_model_call():
    g = _graph()
    ev, llm, _ = run("Alibi table for Garcia", graph=g)
    assert llm.calls == []
    assert ev[0].tools == ["presence_table"]
    call = next(e for e in ev if e.type == "tool_call")
    assert call.tool == "presence_table" and call.arguments["person_id"] == f"p:{S}:garcia"
    assert "Garcia" in call.arguments["names"]
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    assert fin.answer.startswith("Presence table for Garcia in wl: the graph holds 2 places")
    assert "Where: Wisteria Lodge" in fin.answer and "Where: Oxshott Common" in fin.answer
    assert "Who says so: the narrator" in fin.answer
    assert "- Conflict between row 1 and row 2: R1 verdict violated" in fin.answer
    assert {c.quote for c in fin.citations} == {
        "Some time later Garcia looked in at my door",
        "He had been there on Oxshott Common since one o'clock",
    }
    strategy = next(e for e in ev if e.type == "enriched_query").strategy
    assert strategy == "rule-first (presence): no model call"


def test_agent_unknown_person_says_not_found_and_invents_nothing():
    ev, llm, _ = run("Alibi table for Zed Nobody", graph=_graph())
    assert llm.calls == []
    fin = ev[-1]
    assert "no person in the graph named Zed Nobody" in fin.answer
    assert "Where:" not in fin.answer and fin.citations == []


def test_agent_tool_error_and_empty_payload_with_fake_tools():
    g = _graph()
    ev, _, tools = run("Alibi table for Garcia", graph=g, payload_={"error": {"code": "timeout"}})
    # a failed tool is not an answer: same as the timeline, the question goes the text way
    assert tools.calls and "Presence table" not in ev[-1].answer
    ev, _, _ = run(
        "Alibi table for Garcia", graph=g, payload_=payload([], status="insufficient_evidence")
    )
    assert "holds no place" in ev[-1].answer


def test_clock_time_question_still_uses_check_alibi():
    ev, _, tools = run("Where was Garcia at one o'clock?", graph=_graph())
    assert ev[0].tools == ["check_alibi"]
    assert next(e for e in ev if e.type == "tool_call").tool == "check_alibi"
