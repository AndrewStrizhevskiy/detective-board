"""Regression tests for docs/security.md 2.1 (TOCTOU) and 2.3 (server-side deadline)."""

import os
import threading
import time

import pytest

from detective_board.mcp import server, source
from detective_board.mcp.errors import ToolError
from detective_board.mcp.source import JsonFileFactSource

from .conftest import FIXTURE, FIXTURE_DIR


# ---- 2.1 open once, no symlink following ---------------------------------------
def test_symlink_swapped_in_after_resolve_is_not_followed(tmp_path, monkeypatch):
    outside = tmp_path / "outside.json"
    outside.write_bytes(FIXTURE.read_bytes())
    root = tmp_path / "root"
    root.mkdir()
    link = root / "a.json"
    link.symlink_to(outside)
    # simulate the race: the sandbox check saw a regular file, then the path became a symlink
    monkeypatch.setattr(source, "resolve_in_allowlist", lambda p, roots: link)
    src = JsonFileFactSource(str(link), str(root))
    with pytest.raises(ToolError) as ei:
        src.load("s")
    assert ei.value.code == "store_unavailable" and str(outside) not in ei.value.message


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs mkfifo")
def test_non_regular_file_is_rejected_without_blocking(tmp_path, monkeypatch):
    fifo = tmp_path / "f.json"
    os.mkfifo(fifo)
    monkeypatch.setattr(source, "resolve_in_allowlist", lambda p, roots: fifo)
    with pytest.raises(ToolError) as ei:
        JsonFileFactSource(str(fifo), str(tmp_path)).load("s")
    assert ei.value.code == "store_unavailable"


def test_read_is_bounded_by_the_fd_not_by_a_stale_stat(tmp_path, monkeypatch):
    big = tmp_path / "big.json"
    big.write_bytes(b" " * 4096 + FIXTURE.read_bytes())
    monkeypatch.setattr(source, "MAX_BYTES", 1024)
    with pytest.raises(ToolError) as ei:
        JsonFileFactSource(str(big), str(tmp_path)).load("s")
    assert "too large" in ei.value.message


def test_regular_file_still_loads():
    assert JsonFileFactSource(str(FIXTURE), str(FIXTURE_DIR)).load("s").story == "s"


# ---- 2.3 server-side deadline ----------------------------------------------------
def test_deadline_returns_timeout_and_server_stays_responsive():
    gate = threading.Event()
    run = server.DeadlineRunner(0.1)

    def slow():
        gate.wait(5)
        return {"status": "ok"}

    t0 = time.monotonic()
    res = run(slow)
    assert time.monotonic() - t0 < 1.0
    assert res.is_error and res.structured_content["error"]["code"] == "timeout"
    assert res.structured_content["error"]["retriable"] is True
    # while the abandoned call still runs, new calls are refused quickly instead of piling up
    t0 = time.monotonic()
    assert run(lambda: {"status": "ok"}).is_error
    assert time.monotonic() - t0 < 0.5
    gate.set()
    for _ in range(50):
        if not run.busy:
            break
        time.sleep(0.02)
    assert run(lambda: {"status": "ok"}).structured_content == {"status": "ok"}


def test_deadline_runner_keeps_error_normalisation():
    run = server.DeadlineRunner(1.0)

    def boom():
        raise RuntimeError("/home/x/secret")

    res = run(boom)
    assert res.structured_content["error"]["code"] == "internal"
    assert "secret" not in res.content[0].text

    def nf():
        raise ToolError("not_found", "unknown story")

    assert run(nf).structured_content["error"]["code"] == "not_found"


def test_build_server_uses_env_deadline(monkeypatch):
    monkeypatch.setenv(server.ENV_DEADLINE, "0.5")
    assert server.deadline_from_env() == 0.5
    monkeypatch.setenv(server.ENV_DEADLINE, "garbage")
    assert server.deadline_from_env() == server.DEFAULT_DEADLINE_S
