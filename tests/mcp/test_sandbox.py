import os

import pytest
from .conftest import FIXTURE, FIXTURE_DIR

from detective_board.mcp.errors import ToolError
from detective_board.mcp.sandbox import SandboxError, parse_roots, resolve_in_allowlist
from detective_board.mcp.source import JsonFileFactSource


@pytest.fixture
def roots(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "f.json").write_text(FIXTURE.read_text())
    (tmp_path / "secret.json").write_text("{}")
    return tmp_path, allowed, parse_roots(str(allowed))


def test_relative_and_absolute_inside_ok(roots):
    _, allowed, rs = roots
    assert resolve_in_allowlist("f.json", rs) == (allowed / "f.json").resolve()
    assert resolve_in_allowlist(str(allowed / "f.json"), rs) == (allowed / "f.json").resolve()


@pytest.mark.parametrize("bad", ["../secret.json", "sub/../../secret.json", "", "f\x00.json"])
def test_traversal_and_junk_rejected(roots, bad):
    with pytest.raises(SandboxError):
        resolve_in_allowlist(bad, roots[2])


def test_absolute_outside_rejected(roots):
    tmp, _, rs = roots
    with pytest.raises(SandboxError) as ei:
        resolve_in_allowlist(str(tmp / "secret.json"), rs)
    assert str(tmp) not in str(ei.value)
    with pytest.raises(SandboxError):
        resolve_in_allowlist("/etc/passwd", rs)


def test_symlink_escape_rejected_inside_ok(roots):
    tmp, allowed, rs = roots
    os.symlink(tmp / "secret.json", allowed / "evil.json")
    os.symlink(allowed / "f.json", allowed / "good.json")
    os.symlink(tmp, allowed / "dir")
    with pytest.raises(SandboxError):
        resolve_in_allowlist("evil.json", rs)
    with pytest.raises(SandboxError):
        resolve_in_allowlist("dir/secret.json", rs)
    assert resolve_in_allowlist("good.json", rs).name == "f.json"


def test_no_roots_and_directory(roots):
    _, allowed, rs = roots
    with pytest.raises(SandboxError):
        resolve_in_allowlist("f.json", [])
    with pytest.raises(SandboxError):
        resolve_in_allowlist(".", rs)


def test_source_maps_sandbox_failure_to_store_unavailable(roots):
    _, allowed, _ = roots
    src = JsonFileFactSource("../secret.json", str(allowed))
    with pytest.raises(ToolError) as ei:
        src.load("s")
    assert ei.value.code == "store_unavailable"
    assert JsonFileFactSource("f.json", str(allowed)).load("s").story == "s"


def test_source_bad_content(tmp_path):
    (tmp_path / "bad.json").write_text("not json")
    with pytest.raises(ToolError) as ei:
        JsonFileFactSource("bad.json", str(tmp_path)).load("s")
    assert ei.value.code == "store_unavailable"
    with pytest.raises(ToolError):
        JsonFileFactSource(None, str(FIXTURE_DIR)).load("s")
