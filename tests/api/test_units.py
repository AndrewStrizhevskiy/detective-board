import asyncio
import threading
from contextlib import asynccontextmanager

import pytest

from detective_board.api import ApiConfig, load_config
from detective_board.api.sse import frame
from detective_board.api.tool_client import SyncToolClient


def test_sse_frame():
    assert frame("final", '{"a": 1}', 3) == b'event: final\nid: 3\ndata: {"a": 1}\n\n'
    assert frame("x", "l1\nl2") == b"event: x\ndata: l1\ndata: l2\n\n"
    with pytest.raises(ValueError):
        frame("bad\nname", "d")


class FakeSession:
    def __init__(self, delay=0.0):
        self.delay, self.calls, self.threads = delay, [], set()

    async def call_tool(self, name, arguments, *, timeout=5.0):
        self.calls.append((name, arguments))
        self.threads.add(threading.current_thread().name)
        await asyncio.sleep(self.delay)
        return {"status": "ok", "tool": name}


def make_client(session):
    state = {"closed": False}

    @asynccontextmanager
    async def factory():
        try:
            yield session
        finally:
            state["closed"] = True

    return SyncToolClient(factory), state


def test_tool_client_sync_call_and_close():
    s = FakeSession()
    client, state = make_client(s)
    assert client.call("check_alibi", {"story": "x"}, timeout=1) == {
        "status": "ok",
        "tool": "check_alibi",
    }
    out = []
    t = threading.Thread(target=lambda: out.append(client.call("find_overlaps", {}, timeout=1)))
    t.start()
    t.join()
    assert out[0]["status"] == "ok" and s.threads == {"mcp-client"}
    client.close()
    assert state["closed"]


def test_tool_client_timeout_and_startup_failure():
    client, _ = make_client(FakeSession(delay=3.0))
    client.RESULT_MARGIN_S = 0.1
    r = client.call("t", {}, timeout=0.05)
    assert r["error"]["code"] == "timeout"
    client.close()

    @asynccontextmanager
    async def broken():
        raise OSError("cannot spawn")
        yield

    c2 = SyncToolClient(broken)
    r = c2.call("t", {}, timeout=1)
    assert r["error"]["code"] == "store_unavailable" and "OSError" in r["error"]["message"]


def test_config_layers(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('port = 9000\nllm_model = "m"\n[agent]\ntop_k = 7\nmin_score = 0.02\n')
    cfg = load_config(f, env={"DETECTIVE_BOARD_PORT": "9100", "DETECTIVE_BOARD_AGENT_TOP_K": "9"})
    assert (cfg.port, cfg.llm_model, cfg.host) == (9100, "m", "127.0.0.1")
    assert cfg.agent_config().top_k == 9 and cfg.agent_config().min_score == 0.02
    assert load_config(env={}, fake=True).fake is True
    assert load_config(env={"DETECTIVE_BOARD_FAKE": "true"}).fake is True
    assert load_config(env={"DETECTIVE_BOARD_NUM_CTX": "4096"}).num_ctx == 4096


def test_config_rejects_unknown(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("prot = 1\n")
    with pytest.raises(ValueError, match="prot"):
        load_config(f, env={})
    f.write_text("[agent]\ntop_kk = 1\n")
    with pytest.raises(ValueError, match="top_kk"):
        load_config(f, env={})


def test_allowed_hosts():
    assert ApiConfig().allowed_hosts() == ["localhost", "127.0.0.1", "[::1]"]
    assert ApiConfig(host="0.0.0.0").allowed_hosts() == ["*"]
    assert ApiConfig().host == "127.0.0.1"


def test_tool_client_restarts_after_a_transport_failure_and_retries_once():
    starts = []

    class Dying:
        def __init__(self, n):
            self.n = n

        async def call_tool(self, name, arguments, *, timeout=1):
            if self.n == 0:
                raise ConnectionError("child died")
            return {"status": "ok", "session": self.n}

    @asynccontextmanager
    async def factory():
        starts.append(1)
        yield Dying(len(starts) - 1)

    c = SyncToolClient(factory)
    out = c.call("t", {}, timeout=1)
    assert out == {"status": "ok", "session": 1} and c.restarts == 1 and len(starts) == 2
    c.close()


def test_tool_client_failed_start_is_not_retried_every_call():
    now = [0.0]
    n = []

    @asynccontextmanager
    async def broken():
        n.append(1)
        raise OSError("cannot spawn")
        yield

    c = SyncToolClient(broken, clock=lambda: now[0])
    assert c.start() is False
    for _ in range(3):
        assert c.call("t", {}, timeout=1)["error"]["code"] == "store_unavailable"
    assert len(n) == 1
    now[0] = 31.0
    c.call("t", {}, timeout=1)
    assert len(n) == 2
