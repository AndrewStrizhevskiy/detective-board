"""Synchronous `agent.ToolClient` over the async MCP session.

A private event loop runs in a daemon thread and owns the session for its whole life (anyio
cancel scopes must be entered and left by the same task). `call()` blocks the calling worker
thread only. Every failure is returned as the shared error object, never raised."""

from __future__ import annotations

import asyncio
import threading
import time
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
    """Keeps one session alive for the whole life of the app. A transport failure (the child
    died, the pipe closed) restarts the session and repeats the call once; a start that failed is
    not retried before RETRY_START_AFTER_S, so a broken install cannot stall every question."""

    START_WAIT_S = 10.0  # spawn + initialize (docs/mcp-contracts.md section 6)
    RESULT_MARGIN_S = 2.0  # the session enforces `timeout` itself; this is the backstop
    RETRY_START_AFTER_S = 30.0
    server = "timeline-alibi"

    def __init__(self, factory: SessionFactory, *, clock: Callable[[], float] = time.monotonic):
        self._factory = factory
        self._clock = clock
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._session: AsyncSession | None = None
        self._start_error: str | None = None
        self._failed_at: float | None = None
        self._stop: asyncio.Event | None = None
        self.info: dict[str, Any] | None = None  # {"server", "version", "tools"} once started
        self.restarts = 0

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> bool:
        """Spawn the session now (otherwise on the first call). True when it is up."""
        self._ensure_started()
        return self._session is not None

    @property
    def started(self) -> bool:
        return self._session is not None

    def _ensure_started(self) -> None:
        with self._lock:
            t = self._thread
            if t is not None and t.is_alive() and (self._session or not self._ready.is_set()):
                return  # up, or still starting
            if self._failed_at is not None and self._clock() - self._failed_at < (
                self.RETRY_START_AFTER_S
            ):
                return
            ready = self._ready = threading.Event()  # one per start: a late old thread can't signal
            self._start_error = None
            self._thread = threading.Thread(
                target=self._run, args=(ready,), name="mcp-client", daemon=True
            )
            self._thread.start()
        ready.wait(self.START_WAIT_S)
        if self._session is None:
            with self._lock:
                self._failed_at = self._clock()

    def _run(self, ready: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._main(ready))
        finally:
            ready.set()
            loop.close()

    async def _main(self, ready: threading.Event) -> None:
        self._stop = asyncio.Event()
        try:
            async with self._factory() as session:
                describe = getattr(session, "describe", None)
                if describe is not None:
                    self.info = await describe()
                self._session = session
                ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - startup/shutdown failure is reported per call
            self._start_error = type(exc).__name__
        finally:
            self._session = None
            ready.set()

    def close(self) -> None:
        loop, stop, thread = self._loop, self._stop, self._thread
        if loop is not None and stop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:
                pass
        if thread is not None:
            thread.join(timeout=5)

    def _restart(self) -> None:
        self.close()
        with self._lock:
            self._thread = self._loop = self._stop = self._session = None
            self._failed_at = None
            self.restarts += 1

    # -- ToolClient ------------------------------------------------------------------------
    def call(self, tool: str, arguments: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        out = self._call_once(tool, arguments, timeout)
        if out is None:  # transport failure: one restart, one retry
            self._restart()
            out = self._call_once(tool, arguments, timeout)
        if out is None:
            return error_payload("store_unavailable", "MCP server unavailable (connection lost)")
        return out

    def _call_once(
        self, tool: str, arguments: dict[str, Any], timeout: float
    ) -> dict[str, Any] | None:
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
        except Exception:  # noqa: BLE001 - boundary: no stack trace to the agent/UI
            return None
