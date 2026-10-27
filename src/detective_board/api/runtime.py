"""Worker threads that own the SQLite connections, and the cancellable agent run."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from detective_board.api.config import ApiConfig
from detective_board.api.services import RunCancelled, Services, build_services
from detective_board.retrieval import StoreVersionError

log = logging.getLogger("detective_board.api")

_SENTINEL_END = ("end", None)


class Busy(Exception):
    """A run is already in progress (one agent run at a time on a CPU box)."""


class Runtime:
    """Two single-thread executors: `ask` (agent, retrieval, MCP) and `read` (graph / source /
    health lookups). Each builds its own `Services` lazily inside its own thread, so a long
    LLM run never blocks the graph view and no SQLite connection crosses threads."""

    def __init__(self, cfg: ApiConfig) -> None:
        self.cfg = cfg
        self._ask_pool = ThreadPoolExecutor(1, thread_name_prefix="db-ask")
        self._read_pool = ThreadPoolExecutor(1, thread_name_prefix="db-read")
        self._ask_svc: Services | None = None
        self._read_svc: Services | None = None
        self._tls = threading.local()
        self._busy = threading.Lock()
        self._startup_error: str | None = None
        self._closed = False

    # -- read side -------------------------------------------------------------------------
    def _read_services(self) -> Services:
        if self._read_svc is None:
            self._read_svc = build_services(self.cfg, with_agent=False)
        return self._read_svc

    async def read(self, fn: Callable[[Services], Any]) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._read_pool, lambda: fn(self._read_services()))

    def try_read(self, fn: Callable[[Services], Any]) -> tuple[Any, str | None]:
        """Blocking variant for health: (result, None) or (None, error class name)."""
        try:
            return self._read_pool.submit(lambda: fn(self._read_services())).result(), None
        except Exception as exc:  # noqa: BLE001 - reported as "not present", never as a stack trace
            self._startup_error = type(exc).__name__
            return None, type(exc).__name__

    # -- ask side --------------------------------------------------------------------------
    def _is_cancelled(self) -> bool:
        ev = getattr(self._tls, "cancel", None)
        return ev is not None and ev.is_set()

    def _ask_services(self) -> Services:
        if self._ask_svc is None:
            self._ask_svc = build_services(
                self.cfg, with_agent=True, is_cancelled=self._is_cancelled
            )
        return self._ask_svc

    def start_run(
        self,
        question: str,
        history: list[Any],
        cancel: threading.Event,
        put: Callable[[tuple[str, Any]], None],
    ) -> None:
        """Schedule one run; `put(("event", trace_event) | ("error", code) | ("end", None))` is
        called from the worker thread. Raises `Busy` when a run is still active."""
        if not self._busy.acquire(blocking=False):
            raise Busy
        self._ask_pool.submit(self._produce, question, history, cancel, put)

    def _produce(self, question, history, cancel, put) -> None:
        self._tls.cancel = cancel
        gen: Generator[Any, None, None] | None = None
        try:
            svc = self._ask_services()
            assert svc.agent is not None
            gen = cast("Generator[Any, None, None]", svc.agent.ask(question, history))
            for ev in gen:
                if cancel.is_set():
                    break
                put(("event", ev))
        except RunCancelled:
            pass
        except (FileNotFoundError, StoreVersionError):
            log.exception("agent run failed: data not available")
            put(("error", "unavailable"))
        except Exception:
            log.exception("agent run failed")  # details stay in the server log
            put(("error", "internal"))
        finally:
            if gen is not None:
                try:
                    gen.close()
                except BaseException:  # noqa: BLE001
                    pass
            self._tls.cancel = None
            self._busy.release()
            put(_SENTINEL_END)

    @property
    def ask_tools(self) -> Any:
        """The ask side's rule-tool client once it exists (None before the first question)."""
        svc = self._ask_svc
        return svc.tools if svc is not None else None

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def close(self) -> None:
        """Close each service in the thread that created it. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._ask_pool.submit(lambda: self._ask_svc and self._ask_svc.close()).result()
        self._read_pool.submit(lambda: self._read_svc and self._read_svc.close()).result()
        self._ask_pool.shutdown(wait=True)
        self._read_pool.shutdown(wait=True)
