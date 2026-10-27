"""Model-agnostic LLM interface, a scripted FakeLLM and a stdlib Ollama client."""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Protocol

Message = dict[str, str]  # {"role": "system"|"user"|"assistant", "content": str}


class LLM(Protocol):
    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        seed: int | None = None,
        format: dict[str, Any] | None = None,
    ) -> Iterator[str]: ...

    def generate(
        self, prompt: str, *, temperature: float = 0.0, seed: int | None = None
    ) -> Iterator[str]: ...


Script = str | Callable[[Sequence[Message]], str]


class FakeLLM:
    """Deterministic LLM for tests. `script` items are consumed one per call (the last one
    repeats); an item is a string or a function of the messages. Calls are recorded."""

    def __init__(self, script: Script | Iterable[Script] = "") -> None:
        self._script: list[Script] = (
            [script] if isinstance(script, str) or callable(script) else list(script)
        )
        self.calls: list[list[Message]] = []
        self.formats: list[dict[str, Any] | None] = []  # the `format` schema of each chat call

    def _next(self, messages: Sequence[Message]) -> str:
        self.calls.append([dict(m) for m in messages])
        if not self._script:
            return ""
        item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        return item(messages) if callable(item) else item

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        seed: int | None = None,
        format: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        self.formats.append(format)
        text = self._next(messages)
        yield from re.findall(r"\S+\s*|\s+", text)

    def generate(
        self, prompt: str, *, temperature: float = 0.0, seed: int | None = None
    ) -> Iterator[str]:
        return self.chat([{"role": "user", "content": prompt}], temperature=temperature, seed=seed)


# transport(url, payload) -> iterator of NDJSON lines (bytes or str)
Transport = Callable[[str, dict[str, Any]], Iterable[bytes | str]]


def _urllib_transport(timeout: float) -> Transport:
    def post(url: str, payload: dict[str, Any]) -> Iterator[bytes]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (local Ollama)
            yield from resp

    return post


class OllamaLLM:
    """Ollama /api/chat and /api/generate, streaming NDJSON. `think` is the documented
    top-level field; it is off by default (qwen3 would otherwise emit a thinking trace)."""

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        *,
        think: bool = False,
        num_ctx: int | None = None,
        keep_alive: str | None = None,
        timeout: float = 300.0,
        transport: Transport | None = None,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.think = think
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive  # Ollama top-level `keep_alive`, e.g. "30m"
        self._post = transport or _urllib_transport(timeout)

    def _options(
        self, temperature: float, seed: int | None, num_predict: int | None = None
    ) -> dict[str, Any]:
        opts: dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            opts["seed"] = seed
        if num_predict is not None:
            opts["num_predict"] = num_predict
        if self.num_ctx:
            opts["num_ctx"] = self.num_ctx
        return opts

    def _stream(self, path: str, payload: dict[str, Any], field: str) -> Iterator[str]:
        for raw in self._post(self.host + path, payload):
            line = raw.decode() if isinstance(raw, bytes) else raw
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("error"):
                raise RuntimeError(f"ollama error: {obj['error']}")
            piece = (
                obj["message"].get("content", "") if field == "message" else obj.get("response", "")
            )
            if piece:
                yield piece
            if obj.get("done"):
                return

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        seed: int | None = None,
        num_predict: int | None = None,
        format: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": True,
            "think": self.think,
            "options": self._options(temperature, seed, num_predict),
        }
        if format is not None:  # JSON schema: constrained decoding
            payload["format"] = format
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        return self._stream("/api/chat", payload, "message")

    def generate(
        self, prompt: str, *, temperature: float = 0.0, seed: int | None = None
    ) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "think": self.think,
            "options": self._options(temperature, seed),
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        return self._stream("/api/generate", payload, "response")
