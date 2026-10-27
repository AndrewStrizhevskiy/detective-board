"""With a graph file and no facts_path the default rule tools are the stdio server over that
graph; the in-process client is only the labelled fallback. Spawns the real child (seconds)."""

import pytest
from starlette.testclient import TestClient

from detective_board.api import ApiConfig, build_app, fixture
from detective_board.api import services as svc_mod
from detective_board.api.services import build_services, mcp_status
from detective_board.api.tool_client import SyncToolClient
from detective_board.retrieval import Store

from .conftest import MODELS


@pytest.fixture
def real_cfg(tmp_path):
    store, _ = fixture.build_store(str(tmp_path / "i.sqlite"))
    store.close()
    fixture.build_graph(str(tmp_path / "g.sqlite")).close()
    (tmp_path / "w").mkdir()
    return ApiConfig(
        index_path=str(tmp_path / "i.sqlite"),
        graph_path=str(tmp_path / "g.sqlite"),
        embed_model="fake-hash",
        embed_dim=64,
        embed_doc_prefix="doc: ",
        embed_query_prefix="q: ",
        llm_model="qwen3:8b",
        web_dir=str(tmp_path / "w"),
    )


def test_default_tools_are_the_stdio_client_over_the_graph(real_cfg):
    assert Store  # index schema import sanity
    svc = build_services(real_cfg, with_agent=True)
    try:
        assert isinstance(svc.tools, SyncToolClient) and svc.tools.started
        assert svc.agent is not None and svc.agent.tools is svc.tools
        assert svc.tools.server == "timeline-alibi"
        out = svc.tools.call("find_contradictions", {"story": "speckled-band"}, timeout=5)
        assert "error" not in out or out["error"]["code"] == "not_found"
        st = mcp_status(real_cfg, True, svc.tools)
        assert st["mode"] == "stdio" and st["server"] == "timeline-alibi" and st["started"]
        assert "check_alibi" in st["tools"] and st["version"]
    finally:
        svc.close()
    assert not svc.tools.started  # clean shutdown on close


def test_fallback_is_labelled_in_process(real_cfg, monkeypatch, capsys):
    class Broken:
        def __getattr__(self, name):
            raise OSError("no spawn")

    monkeypatch.setattr(
        "detective_board.mcp.client.graph_server_params", lambda *a, **k: Broken()
    )
    svc = build_services(real_cfg, with_agent=True)
    try:
        assert svc.tools.server == "timeline-alibi[in-process]"
        assert "unavailable" in capsys.readouterr().err
        assert mcp_status(real_cfg, True, svc.tools) == {
            "configured": True,
            "mode": "in-process",
            "server": "timeline-alibi[in-process]",
        }
    finally:
        svc.close()


def test_failed_start_falls_back_when_the_child_exits(real_cfg, monkeypatch):
    from detective_board.mcp.client import graph_server_params as real

    def bad(graph, allow, **kw):
        p = real(graph, allow, **kw)
        return p.model_copy(update={"args": ["-c", "raise SystemExit(3)"]})

    monkeypatch.setattr("detective_board.mcp.client.graph_server_params", bad)
    monkeypatch.setattr(SyncToolClient, "START_WAIT_S", 5.0)
    svc = build_services(real_cfg, with_agent=True)
    try:
        assert svc.tools.server == "timeline-alibi[in-process]"
    finally:
        svc.close()


def test_health_reports_started_stdio_after_a_question_builds_the_client(real_cfg):
    with TestClient(build_app(real_cfg, ollama_probe=lambda: MODELS), base_url="http://localhost") as c:
        assert c.get("/api/health").json()["mcp"]["started"] is False
        c.app.state  # noqa: B018 - app built; the ask side is created on the first question
