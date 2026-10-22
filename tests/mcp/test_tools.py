import pytest

from detective_board.mcp import tools
from detective_board.mcp.errors import ToolError
from detective_board.mcp.source import JsonFileFactSource
from detective_board.mcp.tools import Window
from detective_board.symbolic import api
from detective_board.symbolic.api import TimeSpec

from .conftest import FIXTURE, FIXTURE_DIR


@pytest.fixture(scope="module")
def src():
    return JsonFileFactSource(str(FIXTURE), str(FIXTURE_DIR))


@pytest.fixture(scope="module")
def fb(src):
    return src.load("s")


def test_timeline_matches_rules(src, fb):
    out = tools.build_timeline(src, story="s", include_undated=True)
    expected = [r.fact_id for r in api.timeline(fb, include_undated=True)]
    assert [e["event_id"] for e in out["events"]] == expected
    assert out["status"] == "ok" and out["provenance"] == "derived"
    dated = [e for e in out["events"] if e["when"] is not None]
    assert out["undated_count"] == len(expected) - len(api.timeline(fb))
    assert dated and all(e["anchors"] for e in dated)


def test_timeline_filters_and_limit(src):
    out = tools.build_timeline(src, story="s", person_id="W", limit=1)
    assert len(out["events"]) == 1 and out["truncated"] is True
    assert tools.build_timeline(src, story="s", place_id="B")["status"] == "ok"


def test_alibi_equals_direct_call(src, fb):
    out = tools.check_alibi(
        src,
        story="s",
        person_id="W",
        window=Window(story_day=1, start_min=1300, end_min=1310),
        claimed_place_id="B",
    )
    direct = api.check_presence(
        fb,
        person_id="W",
        window=TimeSpec(day=1, lo=1300, hi=1310, exact=True, confidence="high"),
        place_id="B",
    )
    assert out["explanation"] == direct.explanation.model_dump(mode="json")
    assert out["provenance"] == ("conditional" if direct.conditional else "derived")
    assert out["status"] in {"supported", "contradicted", "unknown", "insufficient_evidence"}
    assert out["explanation"]["rule_id"] == "R1" and out["explanation"]["anchors"]


def test_alibi_unknown_ids(src):
    w = Window(start_min=0, end_min=10)
    with pytest.raises(ToolError) as ei:
        tools.check_alibi(src, story="s", person_id="NOPE", window=w)
    assert ei.value.code == "not_found"
    with pytest.raises(ToolError):
        tools.check_alibi(src, story="s", person_id="W", window=w, claimed_place_id="ZZ")
    with pytest.raises(ToolError) as ei:
        tools.build_timeline(src, story="other")
    assert ei.value.code == "not_found"


def test_window_validation():
    with pytest.raises(ValueError):
        Window(start_min=20, end_min=10)
    with pytest.raises(ValueError):
        Window(start_min=0, end_min=2000)
    with pytest.raises(ValueError):
        Window(start_min=0, end_min=1, extra=1)  # type: ignore[call-arg]


def test_limit_validation(src):
    with pytest.raises(ToolError) as ei:
        tools.build_timeline(src, story="s", limit=0)
    assert ei.value.code == "invalid_input"
    with pytest.raises(ToolError):
        tools.find_overlaps(src, story="s", person_ids=[])


def test_overlaps_same_place_vs_any(src):
    same = tools.find_overlaps(src, story="s")
    anyp = tools.find_overlaps(src, story="s", same_place_only=False)
    assert {o["reason_code"] for o in same["overlaps"]} <= {"PLACE_COMPATIBLE"}
    assert len(anyp["overlaps"]) > len(same["overlaps"])
    o = anyp["overlaps"][0]
    assert o["explanation"]["rule_id"] == "R1" and o["provenance"] in {"derived", "conditional"}
    assert len(o["anchors"]) >= 2


def test_contradictions_match_run_all(src, fb):
    out = tools.find_contradictions(src, story="s")
    violated = {
        f.finding_id for r in api.run_all(fb) for f in r.findings if f.verdict.value == "violated"
    }
    assert {f["finding_id"] for f in out["findings"]} == violated
    assert {f["rule"] for f in out["findings"]} == {"R1", "R2", "R3"}
    only = tools.find_contradictions(src, story="s", rules=["R2"])
    assert {f["rule"] for f in only["findings"]} == {"R2"}
