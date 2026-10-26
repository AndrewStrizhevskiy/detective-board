"""Start-up warm-up: load the embedding and answer models and prime Ollama's KV prefix.

Runs once in a background thread, started by the server entry point (never by `build_app`, so
tests and `--fake` are untouched). It is advisory: a failure is recorded, never raised, and a
question that arrives meanwhile simply runs normally (Ollama queues the requests)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from detective_board.agent import OllamaLLM
from detective_board.agent.context import SYSTEM_PROMPT
from detective_board.api.config import ApiConfig
from detective_board.retrieval import EmbeddingConfig, OllamaEmbedder


class Warmup:
    def __init__(self, cfg: ApiConfig, *, llm: Any = None, embedder: Any = None) -> None:
        self.cfg = cfg
        self._llm, self._embedder = llm, embedder
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = "skipped" if cfg.fake or not cfg.warmup else "idle"
        self._embedding: bool | None = None
        self._llm_ok: bool | None = None
        self._seconds: float | None = None
        self._error: str | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "embedding": self._embedding,
                "llm": self._llm_ok,
                "seconds": self._seconds,
                "error": self._error,
            }

    def start(self) -> threading.Thread | None:
        with self._lock:
            if self._state != "idle":
                return None
            self._state = "running"
        self._thread = threading.Thread(target=self.run, name="db-warmup", daemon=True)
        self._thread.start()
        return self._thread

    def _build(self) -> tuple[Any, Any]:
        cfg = self.cfg
        emb = self._embedder or OllamaEmbedder(
            EmbeddingConfig(model=cfg.embed_model, dim=cfg.embed_dim),
            base_url=cfg.ollama_host,
            keep_alive=cfg.keep_alive,
        )
        llm = self._llm or OllamaLLM(
            cfg.llm_model,
            cfg.ollama_host,
            num_ctx=cfg.num_ctx,
            keep_alive=cfg.keep_alive,
            timeout=cfg.llm_timeout_s,
        )
        return emb, llm

    def run(self) -> None:
        t0 = time.monotonic()
        errors: list[str] = []
        try:
            emb, llm = self._build()
        except Exception as exc:  # noqa: BLE001
            emb = llm = None
            errors.append(f"setup: {type(exc).__name__}")
        if emb is not None:
            try:
                emb.embed_query("warm-up")
                with self._lock:
                    self._embedding = True
            except Exception as exc:  # noqa: BLE001 - never fatal
                errors.append(f"embedding: {type(exc).__name__}")
                with self._lock:
                    self._embedding = False
        if llm is not None:
            try:
                # the real static system prompt first, so its KV prefix is reusable by answers
                msgs = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "ok"},
                ]
                for _ in _chat(llm, msgs):
                    pass
                with self._lock:
                    self._llm_ok = True
            except Exception as exc:  # noqa: BLE001
                errors.append(f"llm: {type(exc).__name__}")
                with self._lock:
                    self._llm_ok = False
        with self._lock:
            self._seconds = round(time.monotonic() - t0, 1)
            self._error = "; ".join(errors) or None
            self._state = "failed" if errors else "done"


def _chat(llm: Any, msgs: list[dict[str, str]]):
    chat: Callable[..., Any] = llm.chat
    try:
        return chat(msgs, num_predict=1)
    except TypeError:  # an LLM without num_predict (fakes)
        return chat(msgs)
