"""An Ollama client that lets thinking models think (the project client always sends think=false)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from detective_board.extract.llm import GenRequest, OllamaClient


class ThinkClient(OllamaClient):
    """Same as OllamaClient, but `think` is True for models that report the capability."""

    def build_payload(self, req: GenRequest, caps: Sequence[str]) -> dict[str, Any]:
        payload = super().build_payload(req, caps)
        if "thinking" in caps:
            payload["think"] = True
        return payload
