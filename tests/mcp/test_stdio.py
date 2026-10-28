"""End to end: real server child over stdio. No Ollama, no network."""

import anyio

from detective_board.mcp.client import McpSession, open_session, server_params

from .conftest import FIXTURE, FIXTURE_DIR


async def _bounded(fn):
    with anyio.fail_after(20):
        return await fn()


def _params(facts=str(FIXTURE), allow=str(FIXTURE_DIR)):
    return server_params(facts, allow)


def test_stdio_roundtrip():
    async def go():
        async with open_session(_params()) as s:
            names = await s.list_tools()
            ok = await s.call_tool(
                "check_alibi",
                {
                    "story": "s",
                    "person_id": "W",
                    "claimed_place_id": "B",
                    "window": {"story_day": 1, "start_min": 1300, "end_min": 1310},
                },
            )
            bad = await s.call_tool(
                "check_alibi",
                {"story": "s", "person_id": "W", "window": {"start_min": 9, "end_min": 1}},
            )
            nf = await s.call_tool("build_timeline", {"story": "nope"})
            return names, ok, bad, nf

    names, ok, bad, nf = anyio.run(_bounded, go)
    assert names == [
        "build_timeline",
        "check_alibi",
        "find_contradictions",
        "find_overlaps",
        "presence_table",
        "scene_board",
    ]
    assert ok["status"] == "contradicted"
    assert ok["explanation"]["rule_id"] == "R1" and ok["provenance"] in {"derived", "conditional"}
    assert bad["error"]["code"] == "invalid_input" and "Traceback" not in bad["error"]["message"]
    assert nf["error"]["code"] == "not_found"


def test_stdio_scene_board_matches_in_process():
    from detective_board.mcp import tools
    from detective_board.mcp.source import JsonFileFactSource

    args = {
        "story": "s",
        "place": "B",
        "window": {"story_day": 1, "start_min": 1300, "end_min": 1310},
    }

    async def go():
        async with open_session(_params()) as s:
            return await s.call_tool("scene_board", args)

    out = anyio.run(_bounded, go)
    local = tools.scene_board(
        JsonFileFactSource(str(FIXTURE), str(FIXTURE_DIR)),
        story="s",
        place="B",
        window=tools.Window(**args["window"]),
    )
    assert out == local and out["persons"] and out["rule_id"] == "R1"
    assert any(p["status"] == "excluded" for p in out["persons"])


def test_stdio_sandbox_violation_is_error_not_crash():
    async def go():
        async with open_session(_params(facts="../holmes_mini.json")) as s:
            return await s.call_tool("build_timeline", {"story": "s"})

    res = anyio.run(_bounded, go)
    assert res["error"]["code"] == "store_unavailable"
    assert str(FIXTURE_DIR) not in res["error"]["message"]


def test_client_timeout_returns_error_object():
    class Slow:
        async def call_tool(self, *a, **k):
            await anyio.sleep(5)

    async def go():
        return await McpSession(Slow()).call_tool("x", {}, timeout=0.05)  # type: ignore[arg-type]

    res = anyio.run(go)
    assert res["error"]["code"] == "timeout" and res["error"]["retriable"] is True
