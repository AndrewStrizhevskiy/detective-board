"""Long-context method and bare-model baseline.

`rank_fulltext`: the whole story before the cut (names masked or not) plus the candidate list go to a
mid-size model with a closed answer: a ranking of up to 3 candidates, each with one verbatim quote,
and a confidence. `rank_bare`: the same without the text (does the model know the story?).
Quotes are grounded against the text; the share of grounded quotes is reported.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from detective_board.extract.ground import ground_quote, normalise
from detective_board.extract.llm import GenRequest, LLMClient
from detective_board.suspects.candidates import labels
from detective_board.suspects.common import KV, digest

PROMPT_VERSION = "fulltext-1"

PROMPT_TEXT = """You are a careful detective reasoning from the evidence in a story. The story has been cut: you only have the text up to the moment before the solution is revealed. Question: {question}

Possible answers (choose only from this list):
{options}
- NO_PERSON means: nobody is to blame (an accident, an animal, suicide, natural death).

Rank up to 3 answers, most likely first. For each give a short reason and ONE exact sentence copied from the story as the quote. Judge only by the story text. Give your confidence in the top answer: "low" if the text does not really settle it, "medium", or "high".

STORY:
{text}
"""

PROMPT_BARE = """Question about a Sherlock Holmes story: {question}

Possible answers (choose only from this list):
{options}
- NO_PERSON means: nobody is to blame (an accident, an animal, suicide, natural death).

Rank up to 3 answers, most likely first, and give your confidence in the top answer ("low", "medium" or "high")."""


def schema(options: Sequence[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "ranking": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "string", "enum": list(options)},
                        "reason": {"type": "string"},
                        "quote": {"type": "string"},
                    },
                    "required": ["candidate", "reason", "quote"],
                },
            },
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["ranking", "confidence"],
    }


@dataclass
class Ranking:
    order: list[str]  # candidate labels, best first
    confidence: str
    grounded_quotes: int
    quotes: int
    raw: str = ""


def _run(client, cache, model, prompt, options, num_ctx, text_for_ground, seed) -> Ranking:
    sch = schema(options)
    opts = {"temperature": 0.0, "seed": seed, "num_ctx": num_ctx, "num_predict": 600}
    key = digest(PROMPT_VERSION, model, prompt, opts, sch)
    resp = cache.get(key)
    if resp is None:
        resp = client.generate(
            GenRequest(model=model, prompt=prompt, schema=sch, options=opts)
        ).text
        cache.put(key, resp)
    try:
        data = json.loads(resp)
    except json.JSONDecodeError:
        return Ranking([], "low", 0, 0, resp)
    items = [r for r in data.get("ranking", []) if isinstance(r, dict)]
    norm = normalise(text_for_ground) if text_for_ground else None
    order, seen, good = [], set(), 0
    for r in items:
        cand = r.get("candidate")
        if cand in options and cand not in seen:
            order.append(cand)
            seen.add(cand)
        if norm is not None and ground_quote(str(r.get("quote", "")), norm).grounded != "none":
            good += 1
    conf = data.get("confidence") if data.get("confidence") in ("low", "medium", "high") else "low"
    return Ranking(order, conf, good, len(items), resp)


def rank_fulltext(
    client: LLMClient, cache: KV, *, model: str, question: str, cands, text: str,
    num_ctx: int = 20480, seed: int = 42,
) -> Ranking:  # fmt: skip
    options = labels(cands)
    prompt = PROMPT_TEXT.format(
        question=question, options="\n".join(f"- {o}" for o in options), text=text
    )
    return _run(client, cache, model, prompt, options, num_ctx, text, seed)


def rank_bare(
    client: LLMClient, cache: KV, *, model: str, question: str, cands, seed: int = 42
) -> Ranking:
    options = labels(cands)
    prompt = PROMPT_BARE.format(question=question, options="\n".join(f"- {o}" for o in options))
    return _run(client, cache, model, prompt, options, 4096, "", seed)
