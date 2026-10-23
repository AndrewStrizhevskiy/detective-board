"""FactSource adapter: one JSON file (a serialised FactBase) inside an allowlisted directory."""

from __future__ import annotations

import os
import stat

from pydantic import ValidationError

from detective_board.mcp.errors import ToolError
from detective_board.mcp.sandbox import SandboxError, parse_roots, resolve_in_allowlist
from detective_board.symbolic.api import FactBase

ENV_FACTS = "DETECTIVE_BOARD_FACTS"
ENV_ALLOW = "DETECTIVE_BOARD_FACTS_ALLOW"
MAX_BYTES = 8 * 1024 * 1024


def _read_regular(path: str) -> bytes:
    """Open once (no symlink at the last component, no blocking on FIFOs), check the open fd
    and read at most MAX_BYTES + 1 from it, so a swap or growth after the sandbox check is
    neither followed nor unbounded. Parent components were resolved by the sandbox."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags | getattr(os, "O_NONBLOCK", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError("not a regular file")
        if st.st_size > MAX_BYTES:
            raise ToolError("store_unavailable", "fact file too large")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_BYTES:
            b = os.read(fd, min(1 << 20, MAX_BYTES + 1 - total))
            if not b:
                break
            chunks.append(b)
            total += len(b)
        if total > MAX_BYTES:
            raise ToolError("store_unavailable", "fact file too large")
        return b"".join(chunks)
    finally:
        os.close(fd)


class JsonFileFactSource:
    """Implements symbolic.api.FactSource. Reads the file on every load (cheap, never stale)."""

    def __init__(self, path: str | None, allow: str | None) -> None:
        self.path = path
        self.roots = parse_roots(allow)

    @classmethod
    def from_env(cls) -> JsonFileFactSource:
        return cls(os.environ.get(ENV_FACTS), os.environ.get(ENV_ALLOW))

    def load(self, story: str) -> FactBase:
        if not self.path:
            raise ToolError("store_unavailable", "no fact file configured")
        try:
            real = resolve_in_allowlist(self.path, self.roots)
        except SandboxError as exc:
            raise ToolError("store_unavailable", str(exc)) from None
        try:
            fb = FactBase.model_validate_json(_read_regular(os.fspath(real)))
        except OSError:
            raise ToolError("store_unavailable", "fact file unreadable") from None
        except ValidationError:
            raise ToolError("store_unavailable", "fact file is not a valid FactBase") from None
        if fb.story != story:
            raise ToolError("not_found", f"unknown story: {story!r}")
        return fb
