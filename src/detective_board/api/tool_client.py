"""Synchronous `agent.ToolClient` over the async MCP session.

A private event loop runs in a daemon thread and owns the session for its whole life (anyio
cancel scopes must be entered and left by the same task). `call()` blocks the calling worker
thread only. Every failure is returned as the shared error object, never raised."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from detective_board.mcp.errors import error_payload


class AsyncSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, timeout: float = ...
    ) -> dict[str, Any]: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SyncToolClient:
    START_WAIT_S = 15.0
    RESULT_MARGIN_S = 2.0  # the session enforces `timeout` itself; this is the backstop

    def __init__(self, factory: SessionFactory) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._session: AsyncSession | None = None
        self._start_error: str | None = None
        self._stop: asyncio.Event | None = None

    # -- lifecycle -------------------------------------------------------------------------
    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="mcp-client", daemon=True)
            self._thread.start()
        self._ready.wait(self.START_WAIT_S)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._main())
        finally:
            self._ready.set()
            loop.close()

    async def _main(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with self._factory() as session:
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - startup/shutdown failure is reported per call
            self._start_error = type(exc).__name__
        finally:
            self._session = None
            self._ready.set()

    def close(self) -> None:
        loop, stop, thread = self._loop, self._stop, self._thread
        if loop is not None and stop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:
                pass
        if thread is not None:
            thread.join(timeout=5)

    # -- ToolClient ------------------------------------------------------------------------
    def call(self, tool: str, arguments: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        self._ensure_started()
        session, loop = self._session, self._loop
        if session is None or loop is None:
            msg = "MCP server unavailable" + (
                f" ({self._start_error})" if self._start_error else ""
            )
            return error_payload("store_unavailable", msg)
        fut = asyncio.run_coroutine_threadsafe(
            session.call_tool(tool, arguments, timeout=timeout), loop
        )
        try:
            return fut.result(timeout + self.RESULT_MARGIN_S)
        except TimeoutError:
            fut.cancel()
            return error_payload("timeout", f"tool {tool!r} exceeded {timeout:g}s")
        except Exception as exc:  # noqa: BLE001 - boundary: no stack trace to the agent/UI
            return error_payload("internal", type(exc).__name__)
