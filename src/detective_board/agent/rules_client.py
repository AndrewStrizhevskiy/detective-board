"""In-process `ToolClient`: the `timeline-alibi` tool functions over the graph, without stdio.

The same `detective_board.mcp.tools` functions the MCP server wraps, so a result is identical on
both paths (one source of truth for the rules); only the fact source differs: the live graph
through `SqliteFactSource` instead of one serialised FactBase file. Used in `--fake` demo mode and
when no MCP facts file is configured.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from detective_board.graph import GraphStore, SqliteFactSource
from detective_board.mcp import tools
from detective_board.mcp.errors import ToolError, error_payload

TOOLS = ("build_timeline", "check_alibi", "find_contradictions", "find_overlaps")


class InProcessRulesClient:
    server = "timeline-alibi[in-process]"

    def __init__(self, store: GraphStore, *, assume_day: int | None = None) -> None:
        self.source = SqliteFactSource(store, assume_day=assume_day)

    def call(self, tool: str, arguments: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        """Rules are pure and fast (no model call), so `timeout` is not enforced here."""
        if tool not in TOOLS:
            return error_payload("not_found", f"unknown tool: {tool!r}")
        args = dict(arguments)
        try:
            if tool == "check_alibi":
                args["window"] = tools.Window.model_validate(args.get("window"))
            return getattr(tools, tool)(self.source, **args)
        except ToolError as exc:
            return exc.payload()
        except (ValidationError, ValueError, TypeError) as exc:
            return error_payload("invalid_input", str(exc).splitlines()[0][:200])

    def close(self) -> None:
        pass
