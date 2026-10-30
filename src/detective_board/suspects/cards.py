"""Evidence cards: one closed-schema LLM call per pre-cut chunk, grounded and voted.

The model sees the case question, the candidate labels (plus NO_PERSON) and one passage and
returns up to 3 cards {candidate, effect, kind, quote}. Nothing is trusted until it passes
deterministic checks: the quote is a verbatim span of the passage, and the candidate (any written
form) occurs in the quote or in the sentence before or after it. With `samples` > 1 a (candidate,
effect) pair survives only when a majority of samples produced a grounded card for it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from detective_board.extract.ground import ground_quote, normalise
from detective_board.extract.llm import GenRequest, LLMClient
from detective_board.suspects import NO_PERSON
from detective_board.suspects.candidates import Candidate, labels, mask_text
from detective_board.suspects.common import KV, Chunk, digest, window_around

PROMPT_VERSION = "cards-1"
EFFECTS = ("points_to", "clears")
KINDS = ("motive", "opportunity", "means", "behaviour", "alibi", "statement")

PROMPT = """You are helping to solve a mystery from a detective story. Question: {question}

Possible answers (choose only from this list):
{options}
{no_person_help}

Read the passage. List up to 3 pieces of evidence in it that bear on the question. For each:
- candidate: one name from the list.
- effect: "points_to" if the passage makes that candidate more likely to be responsible, "clears" if it makes them less likely (an alibi, being elsewhere, a gentle or helpless nature, being the victim of a plot).
- kind: motive, opportunity, means, behaviour, alibi or statement.
- quote: ONE exact sentence copied from the passage that shows it.
Only use what the passage says. If the passage has no evidence about the question, return an empty list.

PASSAGE:
{passage}
"""


def schema(options: Sequence[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "string", "enum": list(options)},
                        "effect": {"type": "string", "enum": list(EFFECTS)},
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "quote": {"type": "string"},
                    },
                    "required": ["candidate", "effect", "kind", "quote"],
                },
            }
        },
        "required": ["cards"],
    }


@dataclass(frozen=True)
class Card:
    chunk_id: str
    candidate: str  # label as shown to the model
    effect: str
    kind: str
    quote: str  # grounded span of the original (unmasked) chunk


def build_prompt(question: str, options: Sequence[str], passage: str) -> str:
    opts = "\n".join(f"- {o}" for o in options)
    help_ = (
        f"- {NO_PERSON} means: nobody is to blame (an accident, an animal, suicide, natural death)."
    )
    return PROMPT.format(question=question, options=opts, no_person_help=help_, passage=passage)


def _parse(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    cards = data.get("cards") if isinstance(data, dict) else None
    return [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else []


def ground_cards(
    raw: list[dict], chunk: Chunk, masked_text: str, cands: Sequence[Candidate]
) -> list[Card]:
    """Keep the cards whose quote is verbatim and whose candidate appears near it.

    The quote is matched against the text the model saw (masked or not). The candidate check uses
    that same text, so labels and written forms are both visible to it.
    """
    by_label = {c.label: c for c in cands}
    norm = normalise(masked_text)
    out = []
    for r in raw:
        cand, quote = str(r.get("candidate", "")), str(r.get("quote", ""))
        effect, kind = str(r.get("effect", "")), str(r.get("kind", ""))
        if effect not in EFFECTS or kind not in KINDS:
            continue
        if cand != NO_PERSON and cand not in by_label:
            continue
        g = ground_quote(quote, norm)
        if g.grounded == "none" or not g.span:
            continue
        if cand != NO_PERSON:
            a = masked_text.find(g.span)
            near = window_around(masked_text, a, a + len(g.span)) if a >= 0 else g.span
            c = by_label[cand]
            if cand not in near and not c.matches(near):
                continue
        out.append(Card(chunk.chunk_id, cand, effect, kind, g.span))
    return out


def vote(sample_cards: Sequence[Sequence[Card]]) -> list[Card]:
    """Keep (candidate, effect) pairs found in a majority of the samples; first sample's quote."""
    n = len(sample_cards)
    need = n // 2 + 1
    counts: dict[tuple[str, str], int] = {}
    first: dict[tuple[str, str], Card] = {}
    for cards in sample_cards:
        for key in {(c.candidate, c.effect) for c in cards}:
            counts[key] = counts.get(key, 0) + 1
        for c in cards:
            first.setdefault((c.candidate, c.effect), c)
    return [first[k] for k, v in counts.items() if v >= need]


def cards_for_chunk(
    client: LLMClient,
    cache: KV,
    *,
    model: str,
    question: str,
    cands: Sequence[Candidate],
    chunk: Chunk,
    masked: bool,
    samples: int = 3,
    temperature: float = 0.3,
    seed: int = 42,
    num_ctx: int = 4096,
) -> tuple[list[Card], dict]:
    text = mask_text(chunk.text, cands) if masked else chunk.text
    options = labels(cands)
    prompt = build_prompt(question, options, text)
    sch = schema(options)
    per_sample: list[list[Card]] = []
    stats = {"raw": 0, "grounded": 0, "calls": 0, "cached": 0}
    for k in range(samples):
        opts = {"temperature": 0.0 if samples == 1 else temperature, "seed": seed + k,
                "num_ctx": num_ctx, "num_predict": 700}  # fmt: skip
        key = digest(PROMPT_VERSION, model, prompt, opts, sch)
        resp = cache.get(key)
        if resp is None:
            resp = client.generate(
                GenRequest(model=model, prompt=prompt, schema=sch, options=opts)
            ).text
            cache.put(key, resp)
            stats["calls"] += 1
        else:
            stats["cached"] += 1
        raw = _parse(resp)
        grounded = ground_cards(raw, chunk, text, cands)
        stats["raw"] += len(raw)
        stats["grounded"] += len(grounded)
        per_sample.append(grounded)
    return (vote(per_sample) if samples > 1 else list(per_sample[0])), stats


def all_cards(
    client: LLMClient,
    cache: KV,
    *,
    model: str,
    question: str,
    cands: Sequence[Candidate],
    chunks: Sequence[Chunk],
    masked: bool,
    samples: int = 3,
    workers: int = 4,
    **kw,
) -> tuple[list[Card], dict]:
    def one(ch: Chunk):
        return cards_for_chunk(client, cache, model=model, question=question, cands=cands,
                               chunk=ch, masked=masked, samples=samples, **kw)  # fmt: skip

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, chunks))
    cards = [c for cs, _ in results for c in cs]
    total = {k: sum(s[k] for _, s in results) for k in ("raw", "grounded", "calls", "cached")}
    total["chunks"] = len(chunks)
    return cards, total
