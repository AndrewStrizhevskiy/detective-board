"""Suspects / alibi-exclusion board: router, template and agent level (no Ollama, no model call)."""

import json
import re
from pathlib import Path

import pytest

from detective_board.agent import AgentConfig, FakeLLM
from detective_board.agent.answer import CITATION
from detective_board.agent.honesty import asserts_consistency
from detective_board.agent.router import Router
from detective_board.agent.rule_first import ToolOutcome
from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.agent.scene_answer import (
    HONESTY,
    build_scene_answer,
    is_proper_name,
    scene_board_args,
)
from detective_board.extract import normalise
from detective_board.extract.scenes import SCENE_CURATED_BY, SCENE_MARK, SceneIndex, load_index
from detective_board.extract.schema_v2 import Entity, Event, Extraction
from detective_board.graph import ChunkRef, GraphStore

from .conftest import FakeRetriever, FakeTools, hit, make_agent

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "eval" / "golden"
S = "wl"
T1 = (
    "Eccles slept at Wisteria Lodge, he swore, at one o'clock. Baynes kept watch on Oxshott Common "
    "since one o'clock."
)
T2 = "Garcia lay dead on Oxshott Common since one o'clock, said Gregson. Lucas Moreno said nothing."
CLEAN = T1 + "\n\n" + T2 + "\n"
SCENE = {
    "id": "wl-common-one",
    "story": S,
    "place": "Oxshott Common",
    "day_key": "the-night",
    "time_text": "since one o'clock",
    "start_min": 60,
    "end_min": 60,
    "victim": "Aloysius Garcia",
    "victim_aliases": ["Garcia"],
    "titles": ["Wisteria Lodge"],
    "quote": "Garcia lay dead on Oxshott Common since one o'clock",
    "curated_by": SCENE_CURATED_BY,
    "note": "test scene: every slot is in the quote",
    "inferred": [],
}


@pytest.fixture
def scenes_file(tmp_path):
    d = tmp_path / "data"
    (d / "curated").mkdir(parents=True)
    (d / "clean").mkdir()
    (d / "clean" / f"{S}.txt").write_text(CLEAN, encoding="utf-8")
    start = len(T1) + 2
    chunks = [
        {"chunk_id": f"{S}-0001", "story": S, "char_start": 0, "char_end": len(T1), "text": T1},
        {
            "chunk_id": f"{S}-0002",
            "story": S,
            "char_start": start,
            "char_end": start + len(T2),
            "text": T2,
        },
    ]
    (d / "chunks.jsonl").write_text("\n".join(map(json.dumps, chunks)) + "\n", encoding="utf-8")
    f = d / "curated" / "scenes.jsonl"
    f.write_text(json.dumps(SCENE) + "\n", encoding="utf-8")
    return f


@pytest.fixture
def index(scenes_file) -> SceneIndex:
    return load_index(scenes_file)


def _graph(day) -> GraphStore:
    g = GraphStore()
    person = lambda n: Entity(name=n, type="person", quote=n)  # noqa: E731
    place = lambda n: Entity(name=n, type="place", quote=n)  # noqa: E731
    ev = lambda who, where, t, q: Event(  # noqa: E731
        description=f"{who} at {where}",
        time_text=t,
        place=where,
        participants=[who],
        quote=q,
    )
    c1 = ChunkRef(f"{S}-0001", S, 0, len(T1), T1)
    c2 = ChunkRef(f"{S}-0002", S, len(T1) + 2, len(T1) + 2 + len(T2), T2)
    g.ingest_many(
        [
            (
                c1,
                Extraction(
                    entities=[
                        person("Eccles"),
                        person("Baynes"),
                        place("Wisteria Lodge"),
                        place("Oxshott Common"),
                    ],
                    events=[
                        ev(
                            "Eccles",
                            "Wisteria Lodge",
                            "at one o'clock",
                            "Eccles slept at Wisteria Lodge",
                        ),
                        ev(
                            "Baynes",
                            "Oxshott Common",
                            "since one o'clock",
                            "Baynes kept watch on Oxshott Common",
                        ),
                    ],
                ),
            ),
            (
                c2,
                Extraction(
                    entities=[person("Garcia"), person("Aloysius Garcia"), person("Lucas Moreno")],
                    events=[
                        ev(
                            "Aloysius Garcia",
                            "Oxshott Common",
                            "since one o'clock",
                            "Garcia lay dead on Oxshott Common",
                        ),
                        Event(
                            description="Lucas is silent",
                            participants=["Lucas Moreno"],
                            quote="Lucas Moreno said nothing",
                        ),
                    ],
                ),
            ),
        ]
    )
    for i, n in ((1, 0), (1, 1), (2, 0)):
        g.set_event_day(f"e:{S}-{i:04d}:{n}", day, confidence="high")
    normalise.apply(g, S)
    return g


@pytest.fixture
def graph(index):
    return _graph(index.scenes[0].story_day)


QUESTION = "Who could have been at Oxshott Common at one o'clock?"


def run(question, index, graph, tools=None, hits=None):
    llm = FakeLLM("MODEL TEXT MUST NOT APPEAR")
    retr = FakeRetriever(hits or [hit(1, T1, story=S), hit(2, T2, story=S)])
    tools = tools or InProcessRulesClient(graph)
    agent = make_agent(
        llm, retr, graph=graph, tools=tools, config=AgentConfig(answer_mode="extractive")
    )
    agent.scenes = index
    agent.router = Router(scenes=index)
    return list(agent.ask(question)), llm, tools


def prose(text):
    return CITATION.sub("", text)


# ---- router ----------------------------------------------------------------
@pytest.mark.parametrize(
    "q",
    [
        "Who could have been at Oxshott Common at one o'clock?",
        "Who are the suspects in Wisteria Lodge?",
        "Who can be excluded by alibi in the Wisteria Lodge case?",
        "Who is excluded by an alibi in the Garcia case?",
        "Who was not at the scene of the Garcia murder?",
        "Who was at Oxshott Common?",
        "Who can be ruled out in the Wisteria Lodge case?",
        "List the suspects for the death of Aloysius Garcia",
    ],
)
def test_router_scene_positive(q, index):
    d = Router(scenes=index).decide(q)
    assert d.tools == ["scene_board"] and d.routes == ["mcp", "vector"], q
    assert d.method == "rules" and index.scenes[0].id in d.matched


@pytest.mark.parametrize(
    "q,tools",
    [
        # no scene is known for the story or place: as before
        ("Who are the suspects in Silver Blaze?", []),
        ("Who could have been at Baker Street at nine o'clock?", []),
        ("Who can be excluded by alibi in the Boscombe Valley case?", ["presence_table"]),
        ("Who was at the door of 221B?", []),
        # scene known but not scene wording
        ("Where was Aloysius Garcia at one o'clock?", ["check_alibi"]),
        ("Could Garcia have been at Oxshott Common at one o'clock?", ["check_alibi"]),
        ("What happened on Oxshott Common?", []),
        ("Who killed Aloysius Garcia?", []),
        ("Who is the guilty man in the Wisteria Lodge case?", []),
        # contradiction, timeline and presence-table wording win
        (
            "Is there a conflict about who could have been at Oxshott Common?",
            ["find_contradictions"],
        ),
        ("Give the timeline of who could have been at Oxshott Common", ["build_timeline"]),
        ("Alibi table for the suspects in Wisteria Lodge", ["presence_table"]),
        ("Who says where the suspects in Wisteria Lodge were?", ["presence_table"]),
    ],
)
def test_router_scene_non_matches_and_precedence(q, tools, index):
    d = Router(scenes=index).decide(q)
    assert "scene_board" not in d.tools and d.tools == tools, q


def test_router_without_scenes_is_unchanged():
    for r in (Router(), Router(scenes=SceneIndex())):
        d = r.decide(QUESTION)  # no "could <name> have been": the alibi pattern never matched
        assert d.tools == [] and d.routes == ["vector"]
        assert r.decide("Who are the suspects in Wisteria Lodge?").tools == []


def test_router_golden_sets_do_not_change_with_the_real_scenes():
    """64 + 43 golden questions: the scenes file must not move a single route."""
    f = ROOT / "data" / "curated" / "scenes.jsonl"
    if not f.exists():
        pytest.skip("scenes file not available")
    before, after = Router(), Router(scenes=load_index(f))
    n = 0
    for name in ("questions", "contradictions"):
        for line in (GOLDEN / f"{name}.jsonl").read_text().splitlines():
            q = json.loads(line)["question"]
            a, b = before.decide(q), after.decide(q)
            assert (a.routes, a.tools) == (b.routes, b.tools), q
            n += 1
    assert n == 64 + 43


# ---- template --------------------------------------------------------------
def anchor(quote, start, chunk=f"{S}-0001"):
    return {
        "story": S,
        "chunk_id": chunk,
        "char_start": start,
        "char_end": start + len(quote),
        "quote": quote,
    }


def entry(pid, status, **kw):
    e = {
        "person_id": pid,
        "status": status,
        "alibi_status": {"excluded": "contradicted", "placed": "supported"}.get(status, "unknown"),
        "reason_code": "X",
        "provenance": "derived",
        "placed_events": 0,
        "events_without_day": 0,
        "evidence": [],
        "notes": [],
    }
    return e | kw


def evidence(place, quote, start, at_scene=False, **kw):
    return {
        "kind": "places_person_at_claimed" if at_scene else "places_person_elsewhere",
        "event_id": "e1",
        "place": place,
        "at_scene": at_scene,
        "narrator": True,
        "speaker_id": None,
        "time_text": "at one o'clock",
        "confidence": "high",
        "anchors": [anchor(quote, start)],
    } | kw


def payload(persons, victims=(), **kw):
    counts = {
        k: sum(1 for p in persons if p["status"] == k)
        for k in ("excluded", "placed", "not_excluded")
    }
    p = {
        "status": "ok" if persons else "insufficient_evidence",
        "story": S,
        "place_id": "pl:common",
        "place": "Oxshott Common",
        "window": {"story_day": 1, "start_min": 60, "end_min": 60},
        "persons": list(persons),
        "total_persons": len(persons),
        "counts": counts,
        "victims": list(victims),
        "truncated": False,
        "provenance": "derived",
        "rule_id": "R1",
    }
    return p | kw


def render(p, index, names=None, **kw):
    scene = index.scenes[0]
    a = index.anchor(scene)
    out = [ToolOutcome("scene_board", p)]
    return build_scene_answer(
        scene=scene, anchor=a.as_dict() if a else None, outcomes=out, names=names or {}, **kw
    )


NAMES = {
    "p:eccles": "Eccles",
    "p:baynes": "Baynes",
    "p:lucas": "Lucas Moreno",
    "p:garcia": "Aloysius Garcia",
}


def test_board_lines_for_excluded_placed_and_not_excluded(index):
    persons = [
        entry(
            "p:eccles",
            "excluded",
            evidence=[
                evidence("Wisteria Lodge", "Eccles slept at Wisteria Lodge", 0, curated=True)
            ],
            also_at_scene=False,
        ),
        entry(
            "p:baynes",
            "placed",
            provenance="conditional",
            evidence=[
                evidence(
                    "Oxshott Common",
                    "Baynes kept watch on Oxshott Common",
                    60,
                    True,
                    narrator=False,
                    speaker_id="p:eccles",
                    confidence="low",
                )
            ],
        ),
        entry("p:lucas", "not_excluded", placed_events=2, events_without_day=2),
    ]
    ans = render(payload(persons), index, NAMES)
    t = ans.text
    assert ans.kind == "scene"
    assert t.splitlines()[0].startswith(
        "Alibi board for the scene at Oxshott Common (wl), 01:00 (since one o'clock); "
        "victim: Aloysius Garcia. Scene source: [1:"
    )
    assert f"The scene is {SCENE_MARK}." in t
    assert (
        "Of 3 persons the graph holds for this story, 1 is excluded by testimony, 1 is placed" in t
    )
    assert "1. Eccles: excluded by testimony (label derived)." in t
    assert (
        "Elsewhere: Wisteria Lodge, at one o'clock. Who says so: the narrator. Source: curated "
        '[2: "Eccles slept at Wisteria Lodge"]'
    ) in t
    assert "2. Baynes: placed at the scene (label conditional)." in t
    assert (
        "At the scene: Oxshott Common, at one o'clock. Who says so: Eccles. Source: extracted, low confidence"
        in t
    )
    assert "Conditional because these inputs are low-confidence" in t
    assert (
        "3. Lucas Moreno: not excluded: no placed event at that time (2 placed events, none with a "
        "day and clock time to compare)." in t
    )
    assert HONESTY in t and t.index("1. Eccles") < t.index(HONESTY)
    assert "Travel time between places is not modelled." in t
    assert "Curated: 1 of the facts above" in t
    assert not asserts_consistency(prose(t))


def test_honesty_block_wording_is_fixed(index):
    assert HONESTY == (
        "Excluded means: some account in the text places this person elsewhere at that time; it is "
        "testimony, not proof. Not excluded does not mean suspected. No verdict about guilt is made."
    )
    assert HONESTY in render(payload([entry("p:lucas", "not_excluded")]), index, NAMES).text


def test_nobody_decisive_says_the_graph_is_silent(index):
    persons = [entry("p:lucas", "not_excluded"), entry("p:baynes", "not_excluded", placed_events=1)]
    t = render(payload(persons), index, NAMES).text
    assert "No person is excluded or placed" in t and "the graph is silent" in t
    assert "no placed event for this person in the graph" in t
    assert "1 placed event, none with a day and clock time" in t


def test_excluded_and_also_at_scene_shows_both_accounts(index):
    e = entry(
        "p:eccles",
        "excluded",
        also_at_scene=True,
        evidence=[
            evidence("Wisteria Lodge", "Eccles slept at Wisteria Lodge", 0),
            evidence("Oxshott Common", "Baynes kept watch on Oxshott Common", 60, True),
        ],
    )
    t = render(payload([e]), index, NAMES).text
    assert (
        "Elsewhere: Wisteria Lodge" in t
        and "Also, another account places them at the scene: Oxshott Common" in t
    )


def test_victim_is_not_assessed_and_gets_a_neutral_line(index):
    ev = [
        evidence("Wisteria Lodge", "Eccles slept at Wisteria Lodge", 0),
        evidence("Oxshott Common", "Baynes kept watch on Oxshott Common", 60, True),
    ]
    vic = entry("p:garcia", "excluded", also_at_scene=True, evidence=ev)
    t = render(payload([entry("p:lucas", "not_excluded")], victims=[vic]), index, NAMES).text
    assert "Victim: Aloysius Garcia (not assessed). The accounts differ about where they were" in t
    quiet = render(
        payload([entry("p:lucas", "not_excluded")], victims=[entry("p:garcia", "not_excluded")]),
        index,
        NAMES,
    )
    assert "Victim: Aloysius Garcia (not assessed). No placed event at that time." in quiet.text


@pytest.mark.parametrize(
    "p",
    [
        payload(
            [
                entry(
                    "p:eccles",
                    "excluded",
                    evidence=[evidence("Wisteria Lodge", "Eccles slept at Wisteria Lodge", 0)],
                )
            ]
        ),
        payload(
            [
                entry(
                    "p:baynes",
                    "placed",
                    evidence=[evidence("Oxshott Common", "Baynes kept watch", 60, True)],
                )
            ]
        ),
        payload([entry("p:lucas", "not_excluded")]),
        payload([]),
        {"error": {"code": "not_found", "message": "tool call failed"}},
    ],
)
def test_no_guilt_words_no_ranking_no_consistency_claims(p, index):
    t = render(p, index, NAMES).text
    for word in (
        "guilty",
        "innocent",
        "culprit",
        "murderer",
        "most likely",
        "probably",
        "ranked",
        "likely",
    ):
        assert word not in t.lower(), word
    assert not asserts_consistency(prose(t))
    assert re.search(r"\bguilt\b", t) is None or "No verdict about guilt is made." in t


def test_empty_and_error_payloads(index):
    empty = render(payload([]), index, NAMES)
    assert empty.kind == "empty" and "holds no person" in empty.text
    err = render({"error": {"code": "not_found", "message": "tool call failed"}}, index)
    assert err.kind == "failed" and "No alibi board could be built" in err.text
    assert "No person is reported as excluded or placed" in err.text


def test_other_time_note(index):
    t = render(payload([entry("p:lucas", "not_excluded")]), index, NAMES, other_time=True).text
    assert "The question names a different time" in t
    assert (
        "different time"
        not in render(payload([entry("p:lucas", "not_excluded")]), index, NAMES).text
    )


def test_truncated_board_says_how_many_are_not_listed(index):
    p = payload([entry("p:lucas", "not_excluded")], total_persons=5, truncated=True)
    assert "4 further persons are not listed." in render(p, index, NAMES).text


def test_is_proper_name():
    assert all(is_proper_name(n) for n in ("Baynes", "Scott Eccles", "Mr. Holmes", "Don Murillo"))
    assert not any(
        is_proper_name(n)
        for n in ("the woman", "The report", "the narrator", "Narrator", "Witness", "he", "Fa", "")
    )


# ---- agent level -------------------------------------------------------------
def test_agent_builds_the_board_from_the_graph_without_a_model_call(index, graph):
    ev, llm, _ = run(QUESTION, index, graph)
    assert llm.calls == []
    assert ev[0].tools == ["scene_board"] and ev[0].routes == ["mcp", "vector"]
    call = next(e for e in ev if e.type == "tool_call")
    assert call.tool == "scene_board" and call.server == "timeline-alibi[in-process]"
    assert call.arguments["story"] == S and call.arguments["place"] == "Oxshott Common"
    assert call.arguments["window"] == {
        "story_day": index.scenes[0].story_day,
        "start_min": 60,
        "end_min": 60,
    }
    assert len(call.arguments["victim_ids"]) == 2  # "Aloysius Garcia" and "Garcia"
    res = next(e for e in ev if e.type == "tool_result")
    assert res.ok and res.provenance in {"derived", "conditional"}
    assert res.explanation is not None and res.explanation.rule_id == "R1"
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    t = fin.answer
    assert "Eccles: excluded by testimony" in t
    assert "Baynes: placed at the scene" in t
    assert "Lucas Moreno: not excluded" in t
    assert "Victim: Aloysius Garcia (not assessed)" in t and t.count("Garcia (not assessed)") == 1
    assert HONESTY in t and "Scene source: [1:" in t
    strategy = next(e for e in ev if e.type == "enriched_query").strategy
    assert strategy == "rule-first (scene): no model call"
    quotes = {c.quote for c in fin.citations}
    assert "Garcia lay dead on Oxshott Common since one o'clock" in quotes
    assert "Eccles slept at Wisteria Lodge" in quotes
    assert not asserts_consistency(prose(t))
    # the order of events is the usual one: route, retrieval, tool, answer
    types_ = [e.type for e in ev]
    assert (
        types_.index("retrieval_results") < types_.index("tool_call") < types_.index("tool_result")
    )
    assert types_[-1] == "final" and "graph_query" not in types_


def test_agent_scene_story_comes_from_the_scene_not_from_retrieval(index, graph):
    other = [hit(1, "Holmes said the speckled band was a swamp adder.", story="speckled-band")]
    ev, _, _ = run("Who are the suspects in Wisteria Lodge?", index, graph, hits=other)
    call = next(e for e in ev if e.type == "tool_call")
    assert call.arguments["story"] == S and ev[-1].status == "answered"
    assert ev[-1].answer.startswith("Alibi board for the scene at Oxshott Common")


def test_agent_question_with_other_time_gets_the_note(index, graph):
    ev, _, _ = run("Who could have been at Oxshott Common at nine o'clock?", index, graph)
    assert "The question names a different time" in ev[-1].answer
    ev, _, _ = run(QUESTION, index, graph)
    assert "different time" not in ev[-1].answer


def test_agent_without_a_scene_behaves_as_before(index, graph):
    q = "Who could have been at Baker Street at nine o'clock?"
    ev, llm, tools = run(q, index, graph)
    assert ev[0].tools == [] and ev[0].routes == ["vector"]
    assert all(e.type != "tool_call" or e.tool != "scene_board" for e in ev)
    ev, _, _ = run("Who are the suspects in Silver Blaze?", index, graph)
    assert ev[0].tools == [] and not any(e.type == "tool_call" for e in ev)


def test_agent_tool_failure_goes_the_text_way_not_to_a_board(index, graph):
    ev, _, tools = run(QUESTION, index, graph, tools=FakeTools({"error": {"code": "timeout"}}))
    assert tools.calls and tools.calls[0][0] == "scene_board"
    assert "Alibi board" not in ev[-1].answer


def test_agent_empty_board_payload_is_said_not_invented(index, graph):
    ev, _, _ = run(QUESTION, index, graph, tools=FakeTools(payload([])))
    assert "holds no person" in ev[-1].answer and "Eccles" not in ev[-1].answer


def test_agent_config_scenes_path_loads_the_index(scenes_file, graph):
    agent = make_agent(
        FakeLLM("x"),
        FakeRetriever([hit(1, T1, story=S)]),
        graph=graph,
        tools=InProcessRulesClient(graph),
        config=AgentConfig(scenes_path=str(scenes_file)),
    )
    assert [s.id for s in agent.scenes.scenes] == ["wl-common-one"]
    assert agent.router.decide(QUESTION).tools == ["scene_board"]
    off = make_agent(FakeLLM("x"), config=AgentConfig())
    assert not off.scenes and off.router.decide(QUESTION).tools == []


def test_agent_ignores_an_ungrounded_scenes_file(tmp_path, scenes_file):
    bad = json.loads(scenes_file.read_text()) | {"quote": "Garcia lay dead on the moon"}
    scenes_file.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    agent = make_agent(FakeLLM("x"), config=AgentConfig(scenes_path=str(scenes_file)))
    assert not agent.scenes and agent.router.decide(QUESTION).tools == []
    missing = make_agent(FakeLLM("x"), config=AgentConfig(scenes_path=str(tmp_path / "none.jsonl")))
    assert not missing.scenes


def test_scene_board_args_without_a_scene_or_with_a_fake_graph(index):
    assert scene_board_args(object(), None) is None

    class NoGraph:
        def find_entities(self, *a, **k):
            raise RuntimeError("boom")

    args = scene_board_args(NoGraph(), index.scenes[0])
    assert args and args["victim_ids"] == [] and "person_ids" not in args
