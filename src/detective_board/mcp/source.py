"""FactSource adapter: one JSON file (a serialised FactBase) inside an allowlisted directory."""

from __future__ import annotations

import os

from pydantic import ValidationError

from detective_board.mcp.errors import ToolError
from detective_board.mcp.sandbox import SandboxError, parse_roots, resolve_in_allowlist
from detective_board.symbolic.api import FactBase

ENV_FACTS = "DETECTIVE_BOARD_FACTS"
ENV_ALLOW = "DETECTIVE_BOARD_FACTS_ALLOW"
MAX_BYTES = 8 * 1024 * 1024


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
            if real.stat().st_size > MAX_BYTES:
                raise ToolError("store_unavailable", "fact file too large")
            fb = FactBase.model_validate_json(real.read_bytes())
        except OSError:
            raise ToolError("store_unavailable", "fact file unreadable") from None
        except ValidationError:
            raise ToolError("store_unavailable", "fact file is not a valid FactBase") from None
        if fb.story != story:
            raise ToolError("not_found", f"unknown story: {story!r}")
        return fb
