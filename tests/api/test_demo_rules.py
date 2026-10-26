"""`--fake` demo flavour: contradiction questions run the real rules over the fixture graph."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from starlette.testclient import TestClient

from detective_board.agent.events import TraceEvent
from detective_board.api import build_app, fixture

from .conftest import MODELS, parse_sse

CLEAN = Path(__file__).resolve().parents[2] / "data" / "clean"


@pytest.fixture
def demo(cfg, monkeypatch):
    monkeypatch.setenv("DETECTIVE_BOARD_FIXTURE", "demo")
    with TestClient(build_app(cfg, ollama_probe=lambda: MODELS), base_url="http://localhost") as c:
        yield c


def _ask(client, q):
    r = client.post("/api/ask", json={"question": q})
    assert r.status_code == 200, r.text
    evs = parse_sse(r.text)
    ta = TypeAdapter(TraceEvent)
    for e in evs:  # the event schema is unchanged
        assert ta.validate_json(e["data"]).model_dump_json() == e["data"]
    return [(e["event"], json.loads(e["data"])) for e in evs]


def test_fixture_passages_are_verbatim_with_real_offsets():
    for story, rows in ((fixture.W_STORY, fixture.W_CHUNKS), (fixture.B_STORY, fixture.B_CHUNKS)):
        clean = (CLEAN / f"{story}.txt").read_text(encoding="utf-8")
        for _, start, text in rows:
            assert clean[start : start + len(text)] == text


def test_wisteria_question_streams_a_conditional_r1_finding(demo):
    q = "Is there a conflict about where Garcia was at about one o'clock on the night he died?"
    evs = _ask(demo, q)
    kinds = [k for k, _ in evs]
    for k in ("route_decided", "graph_query", "graph_results", "tool_call", "tool_result"):
        assert k in kinds
    by = dict(evs)
    assert by["graph_query"]["args"]["ref"] == "p:wisteria-lodge:garcia"
    assert by["tool_call"]["server"] == "timeline-alibi[in-process]"
    tr = by["tool_result"]
    assert tr["ok"] and tr["provenance"] == "conditional"
    exp = tr["explanation"]
    assert (exp["rule_id"], exp["verdict"], exp["conditional"]) == ("R1", "violated", True)
    clean = (CLEAN / "wisteria-lodge.txt").read_text(encoding="utf-8")
    assert all(clean[a["char_start"] : a["char_end"]] == a["quote"] for a in exp["anchors"])
    for a in exp["anchors"]:
        r = demo.get(f"/api/source/{a['chunk_id']}", params={"quote": a["quote"]})
        assert r.status_code == 200 and r.json()["highlights"]
    fin = by["final"]
    assert fin["status"] == "answered" and fin["verified"]
    cond = [p for p in fin["provenance"] if p["label"] == "conditional"]
    assert cond and all(p["explanation"]["rule_id"] == "R1" for p in cond)
    assert {c["quote"] for c in fin["citations"]} == {fixture.W_LOOK_QUOTE, fixture.W_SINCE_QUOTE}


def test_mccarthy_question_gets_no_invented_violation(demo):
    q = "Does James McCarthy's testimony contradict what the gamekeeper William Crowder saw?"
    by = dict(_ask(demo, q))
    assert by["graph_query"]["args"]["ref"] == "p:boscombe-valley-mystery:james-mccarthy"
    tr = by["tool_result"]
    assert tr["ok"] and tr["summary"] == "status=ok items=0" and tr["explanation"] is None
    fin = by["final"]
    assert fin["status"] == "answered" and fin["verified"]
    # rule-first: no finding -> the honest template, no model text, no claim of agreement
    assert fin["answer"].startswith("The rule engine found no violation")
    assert "no conflict" not in fin["answer"].lower() and "no contradiction" not in fin["answer"]
    assert "not rule results" in fin["answer"]
    # the passages are source text, never labelled derived
    assert fin["citations"] and {c["label"] for c in fin["citations"]} == {"source_text"}
    assert {p["label"] for p in fin["provenance"]} == {"source_text"}
