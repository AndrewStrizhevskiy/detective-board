"""Dialogue memory: the last N turns, compressed to a bounded text (no model call)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str


def _first_sentence(text: str, limit: int) -> str:
    text = re.sub(r"\[\d+(?:\s*:\s*\".+?\")?\s*\]", "", text, flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r".+?[.!?](?:\s|$)", text)
    s = (m.group(0) if m else text).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def summarize(history: list[Turn] | tuple[Turn, ...], turns: int = 3, max_chars: int = 600) -> str:
    """Newest turns win when the budget is exceeded."""
    lines: list[str] = []
    used = 0
    for t in reversed(list(history)[-turns:] if turns else []):
        line = f"Q: {_first_sentence(t.question, 140)} A: {_first_sentence(t.answer, 160)}"
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(reversed(lines))


_PRONOUN = re.compile(r"\b(he|she|they|him|her|them|his|their|it|that|there)\b", re.I)


def retrieval_query(question: str, history: list[Turn] | tuple[Turn, ...]) -> str:
    """A follow-up with a pronoun and no proper name inherits the previous question."""
    if history and _PRONOUN.search(question) and not re.search(r"(?<!^)\b[A-Z][a-z]+", question):
        return f"{history[-1].question} {question}"
    return question
