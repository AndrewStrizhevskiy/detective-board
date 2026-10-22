"""Router: deterministic rules first, optional LLM classifier fallback. Always records why."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .events import RouteDecided, RouteName
from .llm import LLM

_DOMAIN = re.compile(
    r"holmes|watson|sherlock|baker street|lestrade|moriarty|mycroft|hudson|adler|gregson"
    r"|\bstory\b|\bstories\b|\bcase\b|\bmr\.|\bmrs\.|\bmiss\b|inspector",
    re.I,
)
_OUT = re.compile(
    r"bitcoin|crypto|iphone|smartphone|\bcovid|coronavirus|chatgpt|\bai\b|tesla|trump|biden"
    r"|stock price|weather (today|tomorrow|forecast)|latest news|world cup|\belection\b"
    r"|recipe|programming|python code|\bwrite (me )?(a )?(code|script|poem)",
    re.I,
)
_ALIBI = re.compile(
    r"alibi|where was\b|at what time|what time did|whereabouts|could .{0,40} have been (at|in)",
    re.I,
)
_CONTRA = re.compile(
    r"contradict|conflict|inconsisten|discrepan|doesn'?t add up|does not add up|mismatch", re.I
)
_RELATION = re.compile(
    r"connected|connection|related to|relationship|who knows|acquainted|link between"
    r"|associates?\b|how (is|are|was|were) .{0,60}(related|connected|linked)|ties? between",
    re.I,
)

_CLASSIFY_PROMPT = (
    "Classify the question about the Sherlock Holmes stories into exactly one label: "
    "fact, relation, alibi, contradiction, out_of_scope. Answer with the label only.\n"
    "Question: {q}\nLabel:"
)
_LABEL_ROUTES: dict[str, tuple[list[RouteName], list[str]]] = {
    "fact": (["vector"], []),
    "relation": (["graph", "vector"], []),
    "alibi": (["mcp", "graph", "vector"], ["check_alibi"]),
    "contradiction": (["mcp", "vector"], ["find_contradictions"]),
    "out_of_scope": (["refusal"], []),
}


@dataclass
class Router:
    llm: LLM | None = None
    use_llm: bool = False
    matched: list[str] = field(default_factory=list)

    def decide(self, question: str) -> RouteDecided:
        q = question.strip()
        if _OUT.search(q) and not _DOMAIN.search(q):
            hit = _OUT.search(q).group(0)  # type: ignore[union-attr]
            return RouteDecided(
                routes=["refusal"],
                method="rules",
                matched=[hit],
                confidence=0.9,
                reason=f"question mentions {hit!r}, which is outside the Holmes corpus",
            )
        routes: list[RouteName] = []
        tools: list[str] = []
        matched: list[str] = []
        why: list[str] = []
        if m := _ALIBI.search(q):
            routes += ["mcp", "graph"]
            tools.append("check_alibi")
            matched.append(m.group(0))
            why.append("alibi/time question -> MCP check_alibi + graph events")
        if m := _CONTRA.search(q):
            if "mcp" not in routes:
                routes.append("mcp")
            tools.append("find_contradictions")
            matched.append(m.group(0))
            why.append("contradiction question -> symbolic rules via MCP find_contradictions")
        if m := _RELATION.search(q):
            if "graph" not in routes:
                routes.append("graph")
            matched.append(m.group(0))
            why.append("relation question -> graph query")
        if routes:
            routes.append("vector")
            why.append("hybrid retrieval adds source text")
            return RouteDecided(
                routes=routes,
                tools=tools,
                method="rules",
                matched=matched,
                confidence=0.8,
                reason="; ".join(why),
            )
        if self.use_llm and self.llm is not None:
            label = (
                "".join(self.llm.chat([{"role": "user", "content": _CLASSIFY_PROMPT.format(q=q)}]))
                .strip()
                .lower()
            )
            label = re.sub(r"[^a-z_]", "", label)
            if label in _LABEL_ROUTES:
                r, t = _LABEL_ROUTES[label]
                return RouteDecided(
                    routes=list(r),
                    tools=list(t),
                    method="llm",
                    matched=[label],
                    reason=f"no rule matched; LLM classifier said {label!r}",
                )
        return RouteDecided(
            routes=["vector"],
            method="rules",
            confidence=0.5,
            reason="no special pattern: plain fact question -> hybrid retrieval",
        )


_STOP_START = {
    "who",
    "what",
    "where",
    "when",
    "why",
    "how",
    "was",
    "is",
    "did",
    "does",
    "do",
    "were",
    "are",
    "the",
    "a",
    "an",
    "in",
    "at",
    "on",
    "of",
    "which",
    "tell",
    "list",
    "show",
    "find",
    "can",
    "could",
    "has",
    "have",
    "had",
    "his",
    "her",
    "their",
    "and",
    "but",
    "if",
    "it",
}
_TITLES = {"mr", "mrs", "dr", "sir", "miss"}
_NAME = re.compile(r"(?:(?:Mr|Mrs|Dr|Sir|Miss)\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*")


def extract_names(question: str) -> list[str]:
    """Capitalised word runs (sentence-initial question words dropped), in order, de-duplicated."""
    out: list[str] = []
    for m in _NAME.finditer(question):
        words = m.group(0).split()
        while words and words[0].lower().rstrip(".") in _STOP_START | _TITLES:
            words = words[1:]
        name = " ".join(words)
        if name and name not in out:
            out.append(name)
    return out


_WORD_NUM = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve".split()
    )
}
_TIME = re.compile(
    r"\b(?:at|around|about|by|near)\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|o'?clock)?"
    r"|\b(?:at|around|about|by)\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"(?:\s+o'?clock)?\s*(a\.?m\.?|p\.?m\.?)?",
    re.I,
)


def parse_time_window(question: str) -> tuple[dict[str, int], str] | None:
    """First clock time in the question as a point window {start_min,end_min} plus a note.
    Without am/pm an hour 1-11 is read as p.m. (evening convention); the note says so."""
    m = _TIME.search(question)
    if not m:
        return None
    if m.group(1):
        hour, minute, suffix = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    else:
        hour, minute, suffix = _WORD_NUM[m.group(4).lower()], 0, (m.group(5) or "").lower()
    if hour > 24 or minute > 59:
        return None
    note = "explicit"
    if suffix.startswith("p") and hour < 12:
        hour += 12
    elif suffix.startswith("a") and hour == 12:
        hour = 0
    elif not suffix.startswith(("a", "p")) and 1 <= hour <= 11 and hour <= 12:
        hour += 12
        note = "no a.m./p.m. given: read as p.m."
    t = min(hour * 60 + minute, 1440)
    return {"start_min": t, "end_min": t}, note
