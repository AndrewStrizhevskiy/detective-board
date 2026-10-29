"""Case-file method: a running dossier built chunk by chunk; the final judge sees only the dossier.

For each pre-cut chunk in story order the model gets the current dossier (at most `MAX_ENTRIES`
entries) and the new passage and returns the updated dossier: entries {candidate, effect, kind,
note, quote}, closed enums for names. Every quote must be a verbatim span of some chunk seen so far
(deterministic grounding, the same as for cards); entries that fail are dropped before the next
step. The judge then ranks up to 3 candidates from the dossier alone.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from detective_board.extract.ground import ground_quote, normalise
from detective_board.extract.llm import GenRequest, LLMClient
from detective_board.suspects.candidates import Candidate, labels, mask_text
from detective_board.suspects.cards import EFFECTS, KINDS
from detective_board.suspects.common import KV, Chunk, digest
from detective_board.suspects.fulltext import Ranking, aggregate
from detective_board.suspects.fulltext import schema as rank_schema

PROMPT_VERSION = "dossier-1"
MAX_ENTRIES = 14

PROMPT_STEP = """You keep a case file on a mystery. Question: {question}

Possible answers (choose only from this list):
{options}
- NO_PERSON means: nobody is to blame (an accident, an animal, suicide, natural death).

CURRENT CASE FILE (JSON entries):
{dossier}

NEW PASSAGE:
{passage}

Return the updated case file: keep the entries that still matter, add entries the new passage supports, merge duplicates and drop weak ones. At most {max_entries} entries. Each entry: candidate (from the list), effect ("points_to" = makes them more likely responsible, "clears" = less likely), kind (motive, opportunity, means, behaviour, alibi, statement), note (a few words), quote (ONE exact sentence copied from the passage it came from)."""

PROMPT_JUDGE = """You are a careful detective. Question: {question}

Possible answers (choose only from this list):
{options}
- NO_PERSON means: nobody is to blame (an accident, an animal, suicide, natural death).

You may rely ONLY on this case file; the story text is not available to you.

CASE FILE:
{dossier}

Rank up to 3 answers, most likely first. For each give a short reason and ONE exact quote copied from the case file. Give your confidence in the top answer: "low" if the file does not really settle it, "medium", or "high"."""


def step_schema(options: Sequence[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "maxItems": MAX_ENTRIES,
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "string", "enum": list(options)},
                        "effect": {"type": "string", "enum": list(EFFECTS)},
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "note": {"type": "string"},
                        "quote": {"type": "string"},
                    },
                    "required": ["candidate", "effect", "kind", "note", "quote"],
                },
            }
        },
        "required": ["entries"],
    }


def _call(client, cache, model, prompt, sch, opts) -> str:
    key = digest(PROMPT_VERSION, model, prompt, opts, sch)
    resp = cache.get(key)
    if resp is None:
        resp = client.generate(
            GenRequest(model=model, prompt=prompt, schema=sch, options=opts)
        ).text
        cache.put(key, resp)
    return resp


def build_dossier(
    client: LLMClient, cache: KV, *, model: str, question: str, cands: Sequence[Candidate],
    chunks: Sequence[Chunk], masked: bool, num_ctx: int = 8192, seed: int = 42,
) -> tuple[list[dict], dict]:  # fmt: skip
    options = labels(cands)
    sch = step_schema(options)
    seen_text = ""
    entries: list[dict] = []
    stats = {"steps": 0, "proposed": 0, "kept": 0}
    for ch in chunks:
        shown = mask_text(ch.text, cands) if masked else ch.text
        seen_text += "\n" + shown
        norm = normalise(seen_text)
        prompt = PROMPT_STEP.format(
            question=question, options="\n".join(f"- {o}" for o in options),
            dossier=json.dumps(entries, ensure_ascii=False) if entries else "(empty)",
            passage=shown, max_entries=MAX_ENTRIES,
        )  # fmt: skip
        opts = {"temperature": 0.0, "seed": seed, "num_ctx": num_ctx, "num_predict": 1800}
        try:
            data = json.loads(_call(client, cache, model, prompt, sch, opts))
        except json.JSONDecodeError:
            data = {}
        proposed = [e for e in data.get("entries", []) if isinstance(e, dict)]
        kept = []
        for e in proposed:
            g = ground_quote(str(e.get("quote", "")), norm)
            if (
                e.get("candidate") in options
                and e.get("effect") in EFFECTS
                and e.get("kind") in KINDS
                and g.grounded != "none"
                and g.span
            ):
                kept.append(
                    {**{k: e[k] for k in ("candidate", "effect", "kind", "note")}, "quote": g.span}
                )
        entries = kept[:MAX_ENTRIES]
        stats["steps"] += 1
        stats["proposed"] += len(proposed)
        stats["kept"] += len(entries)
    return entries, stats


def judge_dossier(
    client: LLMClient, cache: KV, *, model: str, question: str, cands: Sequence[Candidate],
    entries: list[dict], num_ctx: int = 8192, seed: int = 42, samples: int = 1, temperature: float = 0.3,
) -> Ranking:  # fmt: skip
    options = labels(cands)
    sch = rank_schema(options)
    dossier = json.dumps(entries, ensure_ascii=False, indent=0) if entries else "(empty)"
    prompt = PROMPT_JUDGE.format(
        question=question, options="\n".join(f"- {o}" for o in options), dossier=dossier
    )

    def one(k: int) -> Ranking:
        t = temperature if samples > 1 else 0.0
        opts = {"temperature": t, "seed": seed + k, "num_ctx": num_ctx, "num_predict": 700}
        resp = _call(client, cache, model, prompt, sch, opts)
        try:
            data = json.loads(resp)
        except json.JSONDecodeError:
            return Ranking([], "low", 0, 0, resp)
        order, seen = [], set()
        for r in data.get("ranking", []):
            c = r.get("candidate") if isinstance(r, dict) else None
            if c in options and c not in seen:
                order.append(c)
                seen.add(c)
        conf = (
            data.get("confidence") if data.get("confidence") in ("low", "medium", "high") else "low"
        )
        return Ranking(order, conf, 0, len(order), resp)

    runs = [one(k) for k in range(max(1, samples))]
    return runs[0] if samples <= 1 else aggregate(runs)
