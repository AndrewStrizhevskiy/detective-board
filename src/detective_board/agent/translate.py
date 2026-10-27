"""Optional query translation: a mostly-Cyrillic question becomes English before retrieval.

The corpus is English and the lexical parts of the pipeline (relevance gate, extractive
scorer, router) only match English words. bge-m3 embeddings are cross-lingual, but a Russian
question would still be refused by the lexical support check. One tiny model call fixes that.
Nothing is translated except the question; the corpus text and the quotes stay English.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .llm import LLM, Message

SYSTEM_PROMPT = (
    "Translate the user's question about Sherlock Holmes stories into English. "
    "Keep names as in the English stories (Holmes, Watson, Roylott, Baskerville...). "
    "Output only the translation."
)
NUM_PREDICT = 60
_CYR = re.compile(r"[Ѐ-ӿ]")
_LETTER = re.compile(r"[^\W\d_]")
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_QUOTES = "\"'`«»“”„‟‘’‚ \t\r\n"


def cyrillic_ratio(text: str) -> float:
    """Share of Cyrillic letters among all letters (0.0 when there are no letters)."""
    letters = _LETTER.findall(text)
    if not letters:
        return 0.0
    return sum(1 for c in letters if _CYR.match(c)) / len(letters)


def is_mostly_cyrillic(text: str, threshold: float = 0.5) -> bool:
    """Deterministic: at least `threshold` of the letters are Cyrillic."""
    return cyrillic_ratio(text) >= threshold


def build_messages(model: str, question: str) -> list[Message]:
    """TranslateGemma documents one user message with a role line and two blank lines before
    the text (Ollama library model card); other models get the system prompt."""
    if model.lower().startswith("translategemma"):
        head = (
            "You are a professional Russian (ru) to English (en) translator. Your goal is to "
            "accurately convey the meaning and nuances of the original Russian text while "
            "adhering to English grammar, vocabulary, and cultural sensitivities. "
            "Names from the Sherlock Holmes stories keep their English spelling. "
            "Produce only the English translation, without any additional explanations or "
            "commentary. Please translate the following Russian text into English:"
        )
        return [{"role": "user", "content": f"{head}\n\n\n{question}"}]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


def validate_translation(raw: str, max_chars: int) -> str | None:
    """The cleaned English text, or None when the output cannot be trusted: empty, still has
    Cyrillic, longer than the cap. Reasoning blocks, wrapping quotes and line breaks are removed."""
    text = _THINK.sub("", raw)
    text = re.sub(r"\s+", " ", text).strip().strip(_QUOTES).strip()
    if not text or _CYR.search(text) or len(text) > max_chars:
        return None
    if not _LETTER.search(text):
        return None
    return text


@dataclass(frozen=True)
class Translation:
    ok: bool
    text: str = ""  # English question when ok
    cached: bool = False
    error: str = ""  # short reason when not ok
    duration_ms: int = 0


class Translator:
    """Translate one question with `llm`; results are cached by (model, text) in memory and,
    when `cache_path` is set, in a JSONL file. Failures are never cached."""

    def __init__(
        self,
        llm: LLM,
        model: str,
        *,
        max_chars: int = 300,
        timeout_s: float = 30.0,
        cache_path: str = "",
        cache_size: int = 256,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        self.llm, self.model = llm, model
        self.max_chars, self.timeout_s = max_chars, timeout_s
        self._path = Path(cache_path) if cache_path else None
        self._size = cache_size
        self._mono = mono
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._loaded = False

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\n{text}".encode()).hexdigest()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None or not self._path.exists():
            return
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                obj = json.loads(line)
                self._remember(obj["key"], obj["text"], persist=False)
        except (OSError, ValueError, KeyError, TypeError):
            self._cache.clear()  # a broken cache file is just a cold cache

    def _remember(self, key: str, text: str, *, persist: bool = True) -> None:
        self._cache[key] = text
        self._cache.move_to_end(key)
        while len(self._cache) > self._size:
            self._cache.popitem(last=False)
        if persist and self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"key": key, "text": text}, ensure_ascii=False) + "\n")
            except OSError:
                pass  # the cache is an optimisation only

    def translate(self, question: str) -> Translation:
        text = question.strip()
        self._load()
        key = self._key(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return Translation(True, self._cache[key], cached=True)
        t0 = self._mono()
        try:
            parts: list[str] = []
            for piece in self.llm.chat(
                build_messages(self.model, text),
                temperature=0.0,
                num_predict=NUM_PREDICT,
            ):
                parts.append(piece)
                if self._mono() - t0 > self.timeout_s:
                    return Translation(False, error="timeout", duration_ms=self._ms(t0))
        except Exception as e:  # model down, HTTP timeout, bad stream: the agent refuses honestly
            return Translation(False, error=type(e).__name__, duration_ms=self._ms(t0))
        out = validate_translation("".join(parts), self.max_chars)
        if out is None:
            return Translation(False, error="invalid_output", duration_ms=self._ms(t0))
        self._remember(key, out)
        return Translation(True, out, duration_ms=self._ms(t0))

    def _ms(self, t0: float) -> int:
        return int((self._mono() - t0) * 1000)
