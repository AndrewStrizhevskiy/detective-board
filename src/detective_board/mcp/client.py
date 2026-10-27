"""Thin MCP client helper: spawn a stdio server, list tools, call one with a timeout."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, StdioServerParameters

from detective_board.mcp.errors import error_payload

DEFAULT_TIMEOUT_S = 5.0
HARD_CAP_S = 15.0
START_TIMEOUT_S = 10.0


def graph_server_params(
    graph: str, allow: str, *, extra_env: dict[str, str] | None = None
) -> StdioServerParameters:
    """Parameters for the `timeline-alibi` server over the graph database (read-only)."""
    from detective_board.mcp.source import ENV_ALLOW, ENV_GRAPH

    src_dir = str(Path(__file__).resolve().parents[2])
    env = {ENV_GRAPH: graph, ENV_ALLOW: allow, "PYTHONPATH": src_dir, **(extra_env or {})}
    return StdioServerParameters(
        command=sys.executable, args=["-m", "detective_board.mcp.server"], env=env
    )


def server_params(
    facts: str, allow: str, *, extra_env: dict[str, str] | None = None
) -> StdioServerParameters:
    """Parameters for the own `timeline-alibi` server (env goes through `env=`, see SDK notes)."""
    from detective_board.mcp.source import ENV_ALLOW, ENV_FACTS

    # The package may not be installed (src layout, no build backend): hand the child its path.
    src_dir = str(Path(__file__).resolve().parents[2])
    env = {ENV_FACTS: facts, ENV_ALLOW: allow, "PYTHONPATH": src_dir, **(extra_env or {})}
    return StdioServerParameters(
        command=sys.executable, args=["-m", "detective_board.mcp.server"], env=env
    )


class McpSession:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def describe(self) -> dict[str, Any]:
        """Server name/version and tool names, as the handshake reported them."""
        info = self._client.server_info
        return {
            "server": getattr(info, "name", None),
            "version": getattr(info, "version", None),
            "tools": await self.list_tools(),
        }

    async def list_tools(self) -> list[str]:
        with anyio.fail_after(START_TIMEOUT_S):
            return sorted(t.name for t in (await self._client.list_tools()).tools)

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, timeout: float = DEFAULT_TIMEOUT_S
    ) -> dict[str, Any]:
        """Return the tool's JSON payload, or the shared error object. Never raises on timeout."""
        timeout = min(timeout, HARD_CAP_S)
        try:
            with anyio.fail_after(timeout):
                res = await self._client.call_tool(name, arguments, read_timeout_seconds=timeout)
        except TimeoutError:
            return error_payload("timeout", f"tool {name!r} exceeded {timeout:g}s")
        payload = res.structured_content
        if payload is None:
            text = "".join(getattr(c, "text", "") for c in res.content)
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
        if isinstance(payload, dict) and (not res.is_error or "error" in payload):
            return payload
        text = "".join(getattr(c, "text", "") for c in res.content)
        code = "invalid_input" if "validation error" in text or "rejected" in text else "internal"
        lines = [ln.strip() for ln in text.splitlines() if "errors.pydantic.dev" not in ln]
        return error_payload(code, " ".join(lines)[:300] or "tool error")


@asynccontextmanager
async def open_session(params: StdioServerParameters) -> AsyncIterator[McpSession]:
    with anyio.fail_after(START_TIMEOUT_S):
        async with Client(params) as client:
            yield McpSession(client)
