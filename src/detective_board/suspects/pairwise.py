"""Pairwise tournament and the cheap 'police accuse' prior.

`accused_by_police`: candidates named in a sentence that also has an arrest or open-accusation
word are what the story's police believe; the prior drops them and ranks the rest by mentions.
`tournament`: for the top-k candidates the model sees the whole pre-cut story and answers
"who is more likely responsible, A or B" for every pair, both orders (position bias is averaged
out); the ranking is the Copeland score.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from itertools import combinations

from detective_board.extract.llm import GenRequest, LLMClient
from detective_board.suspects.candidates import Candidate
from detective_board.suspects.common import KV, Chunk, digest, sentences

PROMPT_VERSION = "pairwise-1"
POLICE = re.compile(
    r"\b(arrest\w*|accus\w*|charged|committed for trial|taken into custody|suspect\w*|"
    r"in custody|warrant|apprehend\w*)\b",
    re.I,
)

PROMPT = """You are a careful detective. The story below is cut before the solution.

STORY:
{text}

Question: {question}
Two possible answers: A = {a} ; B = {b}.
Which of the two is more likely to be the answer, judging only by the story text above? Answer with "A" or "B" and give your confidence ("low", "medium" or "high").
"""
SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["A", "B"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["winner", "confidence"],
}


def accused_by_police(cands: Sequence[Candidate], chunks: Sequence[Chunk]) -> set[str]:
    out: set[str] = set()
    for ch in chunks:
        for a, b in sentences(ch.text):
            s = ch.text[a:b]
            if POLICE.search(s):
                out |= {c.name for c in cands if c.matches(s)}
    return out


def prior_ranking(cands: Sequence[Candidate], chunks: Sequence[Chunk]) -> list[str]:
    """Candidates the police did not accuse, most mentioned first; the accused go last."""
    acc = accused_by_police(cands, chunks)
    ordered = sorted(cands, key=lambda c: -c.mentions)
    return [c.name for c in ordered if c.name not in acc] + [
        c.name for c in ordered if c.name in acc
    ]


def _ask(client, cache, model, question, a, b, text, num_ctx, seed) -> str | None:
    prompt = PROMPT.format(question=question, a=a, b=b, text=text)
    opts = {"temperature": 0.0, "seed": seed, "num_ctx": num_ctx, "num_predict": 60}
    key = digest(PROMPT_VERSION, model, prompt, opts)
    resp = cache.get(key)
    if resp is None:
        resp = client.generate(
            GenRequest(model=model, prompt=prompt, schema=SCHEMA, options=opts)
        ).text
        cache.put(key, resp)
    try:
        w = json.loads(resp).get("winner")
    except json.JSONDecodeError:
        return None
    return a if w == "A" else b if w == "B" else None


def tournament(
    client: LLMClient, cache: KV, *, model: str, question: str, names: Sequence[str], text: str,
    num_ctx: int = 20480, seed: int = 42,
) -> list[str]:  # fmt: skip
    """Copeland ranking of `names` (best first); ties keep the input order."""
    wins = {n: 0.0 for n in names}
    for a, b in combinations(names, 2):
        for x, y in ((a, b), (b, a)):
            w = _ask(client, cache, model, question, x, y, text, num_ctx, seed)
            if w:
                wins[w] += 0.5
    return sorted(names, key=lambda n: (-wins[n], list(names).index(n)))
