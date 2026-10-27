"""The graph-database source and the stdio server over it: read-only, sandboxed, same results as
the in-process client. No Ollama, no network; the spawned server starts in about a second."""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import anyio
import pytest

from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.extract.presence_schema import GroundedFact
from detective_board.graph import ChunkRef, GraphStore, SqliteFactSource
from detective_board.mcp import tools
from detective_board.mcp.client import graph_server_params, open_session
from detective_board.mcp.errors import ToolError
from detective_board.mcp.server import DeadlineRunner
from detective_board.mcp.source import GraphDbFactSource

# curated-facts fixtures (skip when data/ is absent): the Wisteria / Garcia graph
from tests.curated.test_curated import GARCIA_Q, WL, chunks, clean, facts, graph  # noqa: F401

S = "syn"
TEXT = "Ann was at the inn at nine o'clock. Ann was at the park at nine o'clock. Bob said so."


def _gf(place, quote, **kw):
    return GroundedFact(person="Ann", place=place, time_text="nine o'clock", quote=quote, **kw)


@pytest.fixture
def presence_graph(tmp_path):
    """A file graph with presence facts (Ann in two places at once) and a claim-only speaker."""
    from detective_board.extract import normalise
    from detective_board.extract.schema_v2 import Claim, Entity, Extraction

    path = tmp_path / "g" / "graph.sqlite"
    path.parent.mkdir()
    g = GraphStore(str(path))
    c = ChunkRef(f"{S}-0001", S, 0, len(TEXT), TEXT)
    g.ingest_presence(
        c,
        [
            _gf("the inn", "Ann was at the inn at nine o'clock"),
            _gf("the park", "Ann was at the park at nine o'clock"),
        ],
    )
    ex = Extraction(
        entities=[Entity(name="Bob", type="person", quote="Bob")],
        claims=[Claim(speaker="Bob", content="so", quote="Bob said so")],
    )
    bob_text = "Bob said so."
    g.ingest(ChunkRef(f"{S}-0002", S, 200, 200 + len(bob_text), bob_text), ex)
    normalise.apply(g, S)
    yield g, path
    g.close()


def _ids(g, kind):
    return [r[0] for r in g.conn.execute("SELECT id FROM g_node WHERE kind=? ORDER BY id", (kind,))]


def _db_path(g):
    return Path(g.conn.execute("PRAGMA database_list").fetchone()["file"])


def _src(path):
    return GraphDbFactSource(str(path), str(path.parent))


def test_load_equals_the_sqlite_fact_source(presence_graph):
    g, path = presence_graph
    assert _src(path).load(S) == SqliteFactSource(g).load(S)
    assert _src(path).load("*") == SqliteFactSource(g).load("*")


def test_unknown_story_and_claim_only_person(presence_graph):
    g, path = presence_graph
    with pytest.raises(ToolError) as ei:
        _src(path).load("nope")
    assert ei.value.code == "not_found"
    bob = next(i for i in _ids(g, "person") if i.endswith("bob"))
    out = tools.check_alibi(
        _src(path), story=S, person_id=bob, window=tools.Window(start_min=0, end_min=60)
    )
    assert "error" not in out and out["status"] in {"unknown", "insufficient_evidence"}
    assert tools.find_contradictions(_src(path), story=S, person_id=bob)["status"]
    with pytest.raises(ToolError):  # still unknown when he neither speaks nor takes part
        tools.check_alibi(
            _src(path), story=S, person_id="p:syn:zed", window=tools.Window(start_min=0, end_min=1)
        )


def test_read_only_open_cannot_modify_and_does_not_migrate(presence_graph, tmp_path):
    _, path = presence_graph
    before = (path.read_bytes(), os.stat(path).st_mtime_ns)
    src = _src(path)
    src.load(S)
    conn = src._connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO g_overlay(node_id,key,value_json,confidence) VALUES(1,2,3,4)")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM g_node")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE x(a)")
    finally:
        conn.close()
    assert (path.read_bytes(), os.stat(path).st_mtime_ns)[0] == before[0]
    # an empty / foreign file is neither initialised nor migrated
    empty = tmp_path / "e" / "graph.sqlite"
    empty.parent.mkdir()
    sqlite3.connect(empty).close()
    with pytest.raises(ToolError) as ei:
        GraphDbFactSource(str(empty), str(empty.parent)).load("s")
    assert ei.value.code == "store_unavailable"
    con = sqlite3.connect(empty)
    assert con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
    con.close()


def test_reads_while_another_process_connection_writes_wal(tmp_path):
    path = tmp_path / "graph.sqlite"
    w = GraphStore(str(path))
    w.conn.execute("PRAGMA journal_mode=WAL")
    c = ChunkRef(f"{S}-0001", S, 0, len(TEXT), TEXT)
    w.ingest_presence(c, [_gf("the inn", "Ann was at the inn at nine o'clock")])
    src = _src(path)
    n0 = len(src.load(S).events)
    w.conn.execute("BEGIN IMMEDIATE")  # a write transaction stays open while we read
    w.conn.execute("UPDATE g_node SET name=name WHERE 0")
    assert len(src.load(S).events) == n0
    w.conn.execute("COMMIT")
    c2 = ChunkRef(f"{S}-0002", S, 100, 100 + len(TEXT), TEXT)
    w.ingest_presence(c2, [_gf("the park", "Ann was at the park at nine o'clock")])
    assert len(src.load(S).events) == n0 + 1  # the next call sees the committed write
    w.close()


def test_sandbox_rules_for_the_graph_path(presence_graph, tmp_path):
    _, path = presence_graph
    other = tmp_path / "other"
    other.mkdir()
    link = path.parent / "link.sqlite"
    link.symlink_to(other / "graph.sqlite")
    (other / "graph.sqlite").write_bytes(path.read_bytes())
    for bad in (
        GraphDbFactSource(str(path), str(other)),  # outside the allowlist
        GraphDbFactSource(str(path.parent / ".." / "g" / "graph.sqlite"), str(path.parent)),
        GraphDbFactSource(str(link), str(path.parent)),  # symlink escape
        GraphDbFactSource(str(path), None),  # nothing allowed
        GraphDbFactSource(None, str(path.parent)),
    ):
        with pytest.raises(ToolError) as ei:
            bad.load(S)
        assert ei.value.code == "store_unavailable"
        assert str(tmp_path) not in ei.value.message


def test_deadline_applies_to_a_slow_graph_read(presence_graph):
    _, path = presence_graph

    class Slow(GraphDbFactSource):
        def load(self, story):
            time.sleep(1.0)
            return super().load(story)

    run = DeadlineRunner(0.1)
    res = run(lambda: tools.build_timeline(Slow(str(path), str(path.parent)), story=S))
    assert res.is_error and res.structured_content["error"]["code"] == "timeout"
    assert run.busy
    again = run(lambda: {})
    assert again.structured_content["error"]["code"] == "timeout"
    threading.Event().wait(1.2)
    assert not run.busy


# ---- real child over stdio ------------------------------------------------------------------
def _canon(d):
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


async def _stdio_calls(path, calls):
    out = []
    with anyio.fail_after(30):
        async with open_session(graph_server_params(str(path), str(path.parent))) as s:
            info = await s.describe()
            for name, args in calls:
                out.append(await s.call_tool(name, args))
    return info, out


def _calls(story, person, other):
    w = {"story_day": None, "start_min": 540, "end_min": 545}
    return [
        ("find_contradictions", {"story": story}),
        ("find_contradictions", {"story": story, "person_id": person}),
        ("check_alibi", {"story": story, "person_id": person, "window": w}),
        ("find_overlaps", {"story": story, "same_place_only": False}),
        ("build_timeline", {"story": story, "include_undated": True}),
        ("build_timeline", {"story": story, "person_id": other}),  # error object, same both ways
    ]


def _inproc(g, calls):
    c = InProcessRulesClient(g)
    return [c.call(n, a, timeout=5) for n, a in calls]


def test_stdio_over_a_temp_graph_matches_in_process(presence_graph):
    g, path = presence_graph
    ann = next(i for i in _ids(g, "person") if i.endswith("ann"))
    calls = _calls(S, ann, "p:syn:nobody")
    t0 = time.monotonic()
    info, got = anyio.run(_stdio_calls, path, calls)
    assert time.monotonic() - t0 < 15
    assert info["server"] == "timeline-alibi" and "check_alibi" in info["tools"]
    want = _inproc(g, calls)
    assert [_canon(x) for x in got] == [_canon(x) for x in want]
    assert got[0]["status"] and got[-1]["error"]["code"] == "not_found"


def test_stdio_unknown_story_and_sandbox_error_over_the_wire(presence_graph, tmp_path):
    _, path = presence_graph
    _, (nf,) = anyio.run(_stdio_calls, path, [("build_timeline", {"story": "nope"})])
    assert nf["error"]["code"] == "not_found"

    async def bad():
        with anyio.fail_after(30):
            async with open_session(graph_server_params(str(path), str(tmp_path / "x"))) as s:
                return await s.call_tool("build_timeline", {"story": S})

    res = anyio.run(bad)
    assert res["error"]["code"] == "store_unavailable" and str(tmp_path) not in str(res)


def test_stdio_matches_in_process_on_the_curated_graph(graph):  # noqa: F811
    path = _db_path(graph)
    people = [
        r[0]
        for r in graph.conn.execute(
            "SELECT id FROM g_node WHERE kind='person' AND story=? ORDER BY id", (WL,)
        )
    ]
    garcia = next(p for p in people if p.endswith("garcia"))
    calls = _calls(WL, garcia, people[0])
    _, got = anyio.run(_stdio_calls, path, calls)
    want = _inproc(graph, calls)
    assert [_canon(x) for x in got] == [_canon(x) for x in want]
    assert got[0]["findings"], "the curated Garcia conflict must be found over stdio"


def test_garcia_rule_first_answer_is_identical_through_stdio(graph):  # noqa: F811
    from detective_board.agent.rule_first import ToolOutcome, build_answer, coverage_for
    from detective_board.api.tool_client import SyncToolClient

    path = _db_path(graph)
    client = SyncToolClient(lambda: open_session(graph_server_params(str(path), str(path.parent))))
    try:
        assert client.start() and client.server == "timeline-alibi"
        texts = []
        for tc in (InProcessRulesClient(graph), client):
            payload = tc.call("find_contradictions", {"story": WL}, timeout=5)
            ans = build_answer(
                question=GARCIA_Q,
                story=WL,
                outcomes=[ToolOutcome("find_contradictions", payload)],
                link=None,
                notes=[],
                hits=[],
                coverage=coverage_for(tc, graph, WL),
            )
            texts.append(ans.text)
        assert texts[0] == texts[1] and "(curated)" in texts[0]
    finally:
        client.close()
