"""`timeline-alibi` MCP server (stdio). Run: python -m detective_board.mcp.server."""

from __future__ import annotations

import argparse
import json
import os
import threading
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from detective_board.mcp import tools
from detective_board.mcp.errors import ToolError, error_payload
from detective_board.mcp.source import ENV_ALLOW, ENV_FACTS, JsonFileFactSource
from detective_board.mcp.tools import SIZE_CAP_BYTES, Window
from detective_board.symbolic.api import FactSource


def _result(payload: dict[str, Any], is_error: bool = False) -> CallToolResult:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if not is_error:
        for key in ("events", "overlaps", "findings"):
            while len(text.encode()) > SIZE_CAP_BYTES and payload.get(key):
                payload[key] = payload[key][: len(payload[key]) // 2]
                payload["truncated"] = True
                text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=is_error,
    )


ENV_DEADLINE = "DETECTIVE_BOARD_TOOL_DEADLINE_S"
DEFAULT_DEADLINE_S = 4.0  # below the client's default 5 s, so the server answers first


def deadline_from_env() -> float:
    try:
        v = float(os.environ.get(ENV_DEADLINE, ""))
    except ValueError:
        return DEFAULT_DEADLINE_S
    return v if 0 < v <= 60 else DEFAULT_DEADLINE_S


def _call(fn: Callable[[], dict[str, Any]]) -> CallToolResult:
    """Normalise every failure to the shared error object; never leak a stack trace."""
    try:
        return _result(fn())
    except ToolError as exc:
        return _result(exc.payload(), is_error=True)
    except (ValidationError, ValueError) as exc:
        return _result(error_payload("invalid_input", str(exc).splitlines()[0][:200]), True)
    except Exception:  # noqa: BLE001 - boundary: details stay in the server log
        return _result(error_payload("internal", "internal error"), is_error=True)


class DeadlineRunner:
    """Runs each tool call in a daemon thread with a wall-clock deadline. A Python thread cannot
    be killed, so a call that overruns is abandoned; while it still runs, new calls are refused
    at once (`timeout`, retriable) instead of piling more CPU work onto the single stdio server."""

    def __init__(self, deadline_s: float) -> None:
        self.deadline_s = deadline_s
        self._worker: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def __call__(self, fn: Callable[[], dict[str, Any]]) -> CallToolResult:
        if self.busy:
            return _result(
                error_payload("timeout", "a previous call is still running; retry later"), True
            )
        box: list[CallToolResult] = []
        t = threading.Thread(target=lambda: box.append(_call(fn)), daemon=True)
        self._worker = t
        t.start()
        t.join(self.deadline_s)
        if box:
            return box[0]
        return _result(
            error_payload("timeout", f"tool call exceeded {self.deadline_s:g}s"), is_error=True
        )


def build_server(source: FactSource, deadline_s: float | None = None) -> MCPServer:
    mcp = MCPServer("timeline-alibi")
    _run = DeadlineRunner(deadline_s if deadline_s is not None else deadline_from_env())

    @mcp.tool()
    def build_timeline(
        story: str,
        person_id: str | None = None,
        place_id: str | None = None,
        include_undated: bool = False,
        limit: int = 50,
    ) -> CallToolResult:
        """Ordered events of a story (rule R2), optionally for one person/place, with anchors."""
        return _run(
            lambda: tools.build_timeline(
                source,
                story=story,
                person_id=person_id,
                place_id=place_id,
                include_undated=include_undated,
                limit=limit,
            )
        )

    @mcp.tool()
    def check_alibi(
        story: str,
        person_id: str,
        window: Window,
        claimed_place_id: str | None = None,
    ) -> CallToolResult:
        """Rule R1: does the text place the person elsewhere, at the claimed place, or nowhere?"""
        return _run(
            lambda: tools.check_alibi(
                source,
                story=story,
                person_id=person_id,
                window=window,
                claimed_place_id=claimed_place_id,
            )
        )

    @mcp.tool()
    def find_overlaps(
        story: str,
        person_ids: list[str] | None = None,
        same_place_only: bool = True,
        limit: int = 25,
    ) -> CallToolResult:
        """Rule R1: pairs of a person's events that overlap in time (same place, or any place)."""
        return _run(
            lambda: tools.find_overlaps(
                source,
                story=story,
                person_ids=person_ids,
                same_place_only=same_place_only,
                limit=limit,
            )
        )

    @mcp.tool()
    def find_contradictions(
        story: str,
        person_id: str | None = None,
        rules: list[Literal["R1", "R2", "R3"]] | None = None,
        limit: int = 25,
    ) -> CallToolResult:
        """Run rules R1/R2/R3 and list violated findings. Empty list is not proof of consistency."""
        return _run(
            lambda: tools.find_contradictions(
                source, story=story, person_id=person_id, rules=rules, limit=limit
            )
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="timeline-alibi")
    ap.add_argument("--facts", help=f"FactBase JSON file (default: ${ENV_FACTS})")
    ap.add_argument("--allow", help=f"allowed dirs, os.pathsep separated (default: ${ENV_ALLOW})")
    ns = ap.parse_args(argv)
    path = ns.facts or os.environ.get(ENV_FACTS)
    allow = ns.allow or os.environ.get(ENV_ALLOW)
    build_server(JsonFileFactSource(path, allow)).run()


if __name__ == "__main__":
    main()
