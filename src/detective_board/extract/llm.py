"""LLM clients: a small protocol, an Ollama client (stdlib urllib) and a canned fake for tests."""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class GenRequest:
    model: str
    prompt: str
    schema: dict | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenResponse:
    text: str
    done_reason: str | None = None  # "stop" | "length" | ...
    gen_tokens: int | None = None
    prompt_tokens: int | None = None
    wall_s: float = 0.0


class LLMClient(Protocol):
    def generate(self, req: GenRequest) -> GenResponse: ...


class OllamaClient:
    """POST /api/generate with `format` = JSON schema (constrained decoding), non-streaming.

    `think: false` is sent only for models whose /api/show capabilities include "thinking"
    (as in the Phase 0 spike); sending it to other models errors out.
    """

    def __init__(
        self, host: str = "http://localhost:11434", timeout: float = 1800.0, keep_alive: str = "10m"
    ) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive
        self._caps: dict[str, list[str]] = {}

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))

    def capabilities(self, model: str) -> list[str]:
        if model not in self._caps:
            self._caps[model] = self._post("/api/show", {"model": model}).get("capabilities", [])
        return self._caps[model]

    def build_payload(self, req: GenRequest, caps: Sequence[str]) -> dict:
        payload: dict[str, Any] = {
            "model": req.model,
            "prompt": req.prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": dict(req.options),
        }
        if req.schema is not None:
            payload["format"] = req.schema
        if "thinking" in caps:
            payload["think"] = False
        return payload

    def generate(self, req: GenRequest) -> GenResponse:
        payload = self.build_payload(req, self.capabilities(req.model))
        t0 = time.perf_counter()
        r = self._post("/api/generate", payload)
        if r.get("error"):
            raise RuntimeError(str(r["error"])[:200])
        return GenResponse(
            text=r.get("response", ""),
            done_reason=r.get("done_reason"),
            gen_tokens=r.get("eval_count"),
            prompt_tokens=r.get("prompt_eval_count"),
            wall_s=round(time.perf_counter() - t0, 3),
        )


class FakeClient:
    """Returns canned output. `responses`: a callable(prompt) or a list consumed in order."""

    def __init__(self, responses: Callable[[str], str | GenResponse] | Sequence[str | GenResponse]):
        self._responses = responses
        self._i = 0
        self.calls: list[GenRequest] = []

    def generate(self, req: GenRequest) -> GenResponse:
        self.calls.append(req)
        if callable(self._responses):
            out = self._responses(req.prompt)
        else:
            if self._i >= len(self._responses):
                raise RuntimeError("FakeClient: no more canned responses")
            out = self._responses[self._i]
            self._i += 1
        return out if isinstance(out, GenResponse) else GenResponse(text=out, done_reason="stop")
