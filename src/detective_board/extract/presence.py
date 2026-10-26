"""Targeted PRESENCE extraction pass (docs/symbolic-layer.md 11.3).

The generic extraction (extract-2.1) does not give R1/R3 what they need (11.2). This second pass
asks a model for one thing only: "person X was / went / stayed / was seen at place P at time T",
including what a witness says about it, and denials. Outputs are short; every field is then
checked against the fact's own quote (no LLM, same input gives the same output):

 - quote: grounded in the chunk like every other item (`extract/ground.py`); rewritten to the
   chunk's own characters; longer than `MAX_QUOTE_CHARS` is dropped.
 - person: a proper name (no pronoun or description), found in the quote (full name, known alias or
   a surname that is unique among the story's known people); resolved to the graph's canonical name
   when the story is already in the graph (`graph.normalize` keys). Else the fact is dropped.
 - place: a place name or locative noun phrase (`repair._is_place_expression`), never a deictic or
   possessive one ("my door", "there"), found in the quote. Else the fact is dropped.
 - time_text: a temporal expression found in the quote. Else the fact is dropped.
 - day_text: found in the quote, else nulled.
 - source: decided by the chunk's quotation marks (`repair._ChunkIndex.in_speech`), not the model.
 - polarity: 'deny' needs the model's 'deny' AND a negation cue in the quote; 'affirm' with a cue in
   the quote, or 'deny' without one, is ambiguous and the fact is dropped.
 - speaker: kept only for speech and only if a name found in the chunk text.

`lenient=True` (CLI `--lenient`) keeps person/place/time/day values that are NOT in the quote and
lists them in `GroundedFact.context`; the graph marks such facts LOW and never exact. It exists to
compare against the strict default, not as the default.

CLI: python -m detective_board.extract.presence --model M --chunks data/chunks.jsonl
       [--story S ...] [--limit N] --cache data/cache/presence-cache.sqlite
       --graph-db data/graph/graph.sqlite [--out FILE.jsonl] [--lenient]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from detective_board.extract.cache import ExtractCache, cache_key
from detective_board.extract.ground import ground_quote, normalise
from detective_board.extract.llm import GenRequest, LLMClient, OllamaClient
from detective_board.extract.parse import parse_output
from detective_board.extract.pipeline import PROMPT_DIR, Prompt, load_prompt
from detective_board.extract.presence_schema import (
    MAX_FACTS,
    SCHEMA_VERSION,
    GroundedFact,
    PresenceExtraction,
    PresenceFact,
    ollama_format_schema,
)
from detective_board.extract.repair import (
    _NOT_NAMES,
    _ChunkIndex,
    _contains,
    _is_place_expression,
    _is_time_expression,
    _People,
    _Places,
    has_negation,
)
from detective_board.graph.normalize import fold_text, is_unnamed_person, normalize_name

__all__ = [
    "DEFAULT_PROMPT",
    "SCHEMA_VERSION",
    "GroundedFact",
    "KnownEntities",
    "PresenceConfig",
    "PresenceExtraction",
    "PresenceExtractor",
    "PresenceFact",
    "PresenceResult",
    "build_report",
    "ground_facts",
    "known_from_graph",
    "ollama_format_schema",
]

DEFAULT_PROMPT = PROMPT_DIR / "presence_v1.txt"
MAX_QUOTE_CHARS = 500
# A place starting with one of these is no name for the rules ("my door", "there", "his home").
DEICTIC = frozenset(
    "my his her their our your its here there this that these those home where which".split()
)

# A noun phrase right after one of these (optionally via an article) is taken as a place even if
# it is not a capitalised name or one of repair's locative nouns: "in the conservatory".
LOCATIVE = frozenset(
    "at in on upon to into onto near by from inside within outside beside towards toward through "
    "across along under behind beyond round around".split()
)

Entities = list[dict[str, Any]]


@dataclass
class KnownEntities:
    """Persons and places the graph already knows for a story: (canonical name, aliases)."""

    people: list[tuple[str, list[str]]] = field(default_factory=list)
    places: list[tuple[str, list[str]]] = field(default_factory=list)

    def person_entities(self) -> Entities:
        return [{"type": "person", "name": n, "aliases": a} for n, a in self.people]

    def place_entities(self) -> Entities:
        return [{"type": "place", "name": n, "aliases": a} for n, a in self.places]


def known_from_graph(store: Any, story: str) -> KnownEntities:
    """Named persons and places of `story` in a GraphStore (display name + aliases)."""
    out = KnownEntities()
    for kind, dest in (("person", out.people), ("place", out.places)):
        rows = store.conn.execute(
            "SELECT name, props_json FROM g_node WHERE story=? AND kind=? AND unnamed=0"
            " ORDER BY id",
            (story, kind),
        )
        for r in rows:
            if r["name"]:
                dest.append((r["name"], list(json.loads(r["props_json"]).get("aliases", []))))
    return out


@dataclass(frozen=True)
class PresenceConfig:
    model: str
    num_ctx: int = 4096
    num_predict: int = 768  # outputs are short: at most 6 facts
    seed: int = 42
    temperature: float = 0.0
    fuzzy_threshold: float = 0.85
    lenient: bool = False  # grounding only; not part of the cache key

    def options(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
        }


# --------------------------------------------------------------------------- grounding


def _is_name(key: str) -> bool:
    toks = key.split()
    return bool(toks) and not all(t in _NOT_NAMES for t in toks)


def _ground_person(
    text: str, qf: str, people: _People, lenient: bool
) -> tuple[str | None, bool, str | None]:
    """(name, in_quote, reject code). `name` is the graph's canonical name when known."""
    key = normalize_name(text)
    if is_unnamed_person(text) or not _is_name(key):
        return None, False, "PERSON_NOT_A_NAME"
    ei = people.entity_of(text)
    keys = {key}
    if ei is not None:
        keys |= {k for k, e in people.key_to_ent.items() if e == ei}
    else:
        toks = key.split()
        known_surnames = {k.split()[-1] for k in people.key_to_ent} | {
            normalize_name(n).split()[-1] for n in people.names if normalize_name(n)
        }
        if len(toks) >= 2 and len(toks[-1]) >= 3 and toks[-1] not in known_surnames:
            keys.add(toks[-1])  # nobody known shares the surname: it identifies the person
    in_quote = any(_contains(qf, k) for k in keys)
    name = people.entities[ei]["name"] if ei is not None else text.strip()
    if not in_quote and not lenient:
        return None, False, "PERSON_NOT_IN_QUOTE"
    return name, in_quote, None


def _after_locative(qf: str, keys: Sequence[str]) -> bool:
    """True if some key occurs in the folded quote right after a locative preposition."""
    toks = qf.split()
    for k in keys:
        kt = k.split()
        for i in range(len(toks) - len(kt) + 1):
            if toks[i : i + len(kt)] == kt:
                j = i - 1
                if j >= 0 and toks[j] in ("the", "a", "an"):
                    j -= 1
                if j >= 0 and toks[j] in LOCATIVE:
                    return True
    return False


def _ground_place(
    text: str, qf: str, chunk_text: str, places: _Places, lenient: bool
) -> tuple[str | None, bool, str | None]:
    p = text.strip()
    toks = fold_text(p).split()
    if not toks:
        return None, False, "PLACE_EMPTY"
    if toks[0] in DEICTIC:
        return None, False, "PLACE_DEICTIC"
    keys = sorted(places.keys(p))
    in_quote = any(_contains(qf, k) for k in keys)
    if not lenient and not (
        _is_place_expression(p, chunk_text, places) or (in_quote and _after_locative(qf, keys))
    ):
        return None, False, "PLACE_NOT_A_PLACE"
    if not in_quote and not lenient:
        return None, False, "PLACE_NOT_IN_QUOTE"
    return p, in_quote, None


def _ground_time(
    text: str, qf: str, quote: str, lenient: bool
) -> tuple[str | None, bool, str | None]:
    t = text.strip()
    if not _is_time_expression(t, quote):
        return None, False, "TIME_NOT_TEMPORAL"
    in_quote = _contains(qf, fold_text(t))
    if not in_quote and not lenient:
        return None, False, "TIME_NOT_IN_QUOTE"
    return t, in_quote, None


def _ground_speaker(
    text: str | None, chunk_f: str, people: _People
) -> tuple[str | None, str | None]:
    if not text or not text.strip():
        return None, None
    key = normalize_name(text)
    if is_unnamed_person(text) or not _is_name(key):
        return None, "SPEAKER_NOT_A_NAME"
    ei = people.entity_of(text)
    keys = {key} | (
        {k for k, e in people.key_to_ent.items() if e == ei} if ei is not None else set()
    )
    if not any(_contains(chunk_f, k) for k in keys):
        return None, "SPEAKER_NOT_IN_CHUNK"
    return (people.entities[ei]["name"] if ei is not None else text.strip()), None


@dataclass
class GroundOutcome:
    facts: list[GroundedFact] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    grounding: dict[str, int] = field(default_factory=lambda: {"exact": 0, "fuzzy": 0, "none": 0})


def ground_facts(
    raw: Sequence[PresenceFact],
    chunk_text: str,
    known: KnownEntities | None = None,
    *,
    fuzzy_threshold: float = 0.85,
    lenient: bool = False,
    start_idx: int = 0,
) -> GroundOutcome:
    """Deterministic grounding of the model's presence facts against one chunk (see module doc)."""
    known = known or KnownEntities()
    out = GroundOutcome()
    chunk_n = normalise(chunk_text)
    chunk_f = fold_text(chunk_text)
    index = _ChunkIndex(chunk_text)
    people = _People(known.person_entities())
    places = _Places(known.place_entities())
    seen: set[tuple[str, ...]] = set()

    def drop(i: int, reason: str, quote: str) -> None:
        out.dropped.append({"kind": "facts", "idx": i, "reason": reason, "quote": quote})

    for i, f in enumerate(raw, start_idx):
        if len(out.facts) >= MAX_FACTS:
            drop(i, "over_limit", f.quote)
            continue
        g = ground_quote(f.quote, chunk_n, threshold=fuzzy_threshold)
        out.grounding[g.grounded] += 1
        if g.span is None:
            drop(i, "quote_not_grounded", f.quote)
            continue
        quote = g.span
        if len(quote) > MAX_QUOTE_CHARS:
            drop(i, "quote_too_long", quote)
            continue
        qf = fold_text(quote)
        codes: list[str] = []
        context: list[str] = []
        if g.grounded == "fuzzy":
            codes.append("QUOTE_FUZZY")

        person, in_q, why = _ground_person(f.person, qf, people, lenient)
        if why or person is None:
            drop(i, why or "PERSON_NOT_A_NAME", quote)
            continue
        if not in_q:
            context.append("person")
        place, in_q, why = _ground_place(f.place, qf, chunk_text, places, lenient)
        if why or place is None:
            drop(i, why or "PLACE_EMPTY", quote)
            continue
        if not in_q:
            context.append("place")
        time_text, in_q, why = _ground_time(f.time_text, qf, quote, lenient)
        if why or time_text is None:
            drop(i, why or "TIME_NOT_TEMPORAL", quote)
            continue
        if not in_q:
            context.append("time_text")

        day_text = None
        if f.day_text and f.day_text.strip():
            d = f.day_text.strip()
            if _is_time_expression(d, quote) and _contains(qf, fold_text(d)):
                day_text = d
            elif lenient and _is_time_expression(d, quote):
                day_text = d
                context.append("day_text")
            else:
                codes.append("DAY_NOT_IN_QUOTE")

        cue = has_negation(quote)
        if (f.polarity == "deny") != cue:
            drop(i, "POLARITY_UNCLEAR", quote)
            continue

        located = index.in_speech(quote)
        source = "speech" if located else "narrator"
        if source != f.source:
            codes.append("SOURCE_CHANGED")
        speaker = None
        if source == "speech":
            speaker, why = _ground_speaker(f.speaker, chunk_f, people)
            if why:
                codes.append(why)
        key = (
            fold_text(person),
            fold_text(place),
            fold_text(time_text),
            f.polarity,
            fold_text(quote),
        )
        if key in seen:
            drop(i, "duplicate", quote)
            continue
        seen.add(key)
        out.facts.append(
            GroundedFact(
                person=person,
                place=place,
                time_text=time_text,
                day_text=day_text,
                polarity=f.polarity,
                source=source,
                speaker=speaker,
                quote=quote,
                context=context,
                codes=codes,
                model_values=f.model_dump(),
            )
        )
    return out


# --------------------------------------------------------------------------- per chunk


@dataclass
class PresenceResult:
    chunk_id: str
    story: str
    status: str  # ok | repaired | failed | error
    facts: list[dict[str, Any]] = field(default_factory=list)  # GroundedFact dumps
    n_model_facts: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    grounding: dict[str, int] = field(default_factory=lambda: {"exact": 0, "fuzzy": 0, "none": 0})
    truncated: bool = False
    cached: bool = False
    wall_s: float = 0.0
    error: str | None = None
    model: str = ""
    prompt_version: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id, "story": self.story, "status": self.status,
            "truncated": self.truncated, "cached": self.cached, "wall_s": self.wall_s,
            "error": self.error, "model": self.model, "prompt_version": self.prompt_version,
            "schema_version": self.schema_version, "grounding": self.grounding,
            "n_model_facts": self.n_model_facts, "dropped": self.dropped, "facts": self.facts,
        }  # fmt: skip

    def grounded_facts(self) -> list[GroundedFact]:
        return [GroundedFact.model_validate(f) for f in self.facts]


class PresenceExtractor:
    def __init__(
        self,
        client: LLMClient,
        cfg: PresenceConfig,
        cache: ExtractCache | None = None,
        prompt: Prompt | None = None,
    ) -> None:
        self.client = client
        self.cfg = cfg
        self.cache = cache
        self.prompt = prompt or load_prompt(DEFAULT_PROMPT)
        self._schema = ollama_format_schema()

    def key(self, text: str) -> str:
        """Model, prompt version, schema version 'presence-1' and options are all in the key."""
        return cache_key(
            text, self.cfg.model, self.prompt.version, SCHEMA_VERSION, self.cfg.options()
        )

    def _raw(self, text: str) -> tuple[dict | None, bool, str | None]:
        key = self.key(text)
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            return hit, True, None
        req = GenRequest(self.cfg.model, self.prompt.render(text), self._schema, self.cfg.options())
        try:
            r = self.client.generate(req)
        except Exception as e:  # network/model error: not cached, chunk marked error
            return None, False, f"{type(e).__name__}: {str(e)[:200]}"
        rec = {"text": r.text, "done_reason": r.done_reason, "gen_tokens": r.gen_tokens,
               "prompt_tokens": r.prompt_tokens, "wall_s": r.wall_s}  # fmt: skip
        if self.cache is not None:
            self.cache.put(key, rec)
        return rec, False, None

    def extract_chunk(
        self, chunk_id: str, story: str, text: str, known: KnownEntities | None = None
    ) -> PresenceResult:
        res = PresenceResult(
            chunk_id, story, "error", model=self.cfg.model, prompt_version=self.prompt.version
        )
        rec, cached, err = self._raw(text)
        if rec is None:
            res.error = err
            return res
        res.cached, res.wall_s = cached, float(rec.get("wall_s") or 0.0)
        res.truncated = rec.get("done_reason") == "length"
        parsed = parse_output(rec["text"])
        res.status, res.error = parsed.status, parsed.error
        if parsed.data is None:
            return res
        items = parsed.data.get("facts", [])
        if not isinstance(items, list):
            res.dropped.append({"kind": "facts", "idx": -1, "reason": "not_a_list", "quote": None})
            return res
        valid: list[PresenceFact] = []
        known_keys = set(PresenceFact.model_fields)
        for idx, it in enumerate(items):
            q = it.get("quote") if isinstance(it, dict) else None
            if not isinstance(it, dict):
                res.dropped.append(
                    {"kind": "facts", "idx": idx, "reason": "not_an_object", "quote": None}
                )
                continue
            try:
                valid.append(
                    PresenceFact.model_validate({k: v for k, v in it.items() if k in known_keys})
                )
            except ValidationError as e:
                err0 = e.errors()[0]
                reason = f"{err0['type']}:{'.'.join(str(x) for x in err0['loc'])}"[:80]
                res.dropped.append({"kind": "facts", "idx": idx, "reason": reason, "quote": q})
        res.n_model_facts = len(items)
        out = ground_facts(
            valid,
            text,
            known,
            fuzzy_threshold=self.cfg.fuzzy_threshold,
            lenient=self.cfg.lenient,
        )
        res.dropped += out.dropped
        res.grounding = out.grounding
        res.facts = [f.model_dump() for f in out.facts]
        return res


# --------------------------------------------------------------------------- CLI


def build_report(results: Sequence[PresenceResult]) -> dict:
    n = len(results)
    live = [r for r in results if not r.cached and r.status != "error"]
    g = {"exact": 0, "fuzzy": 0, "none": 0}
    reasons: dict[str, int] = {}
    for r in results:
        for k in g:
            g[k] += r.grounding[k]
        for d in r.dropped:
            reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
    model_facts = sum(r.n_model_facts for r in results)
    kept = [f for r in results for f in r.facts]
    return {
        "chunks": n,
        "from_cache": sum(r.cached for r in results),
        "errors": sum(r.status == "error" for r in results),
        "valid_json_rate": round(sum(r.status == "ok" for r in results) / n, 3) if n else 0.0,
        "repaired": sum(r.status == "repaired" for r in results),
        "failed": sum(r.status == "failed" for r in results),
        "truncated": sum(r.truncated for r in results),
        "chunks_with_facts": sum(bool(r.facts) for r in results),
        "facts_model": model_facts,
        "facts_kept": len(kept),
        "facts_dropped": len([d for r in results for d in r.dropped]),
        "fact_survival_rate": round(len(kept) / model_facts, 3) if model_facts else 0.0,
        "dropped_by_reason": dict(sorted(reasons.items())),
        "kept_speech": sum(f["source"] == "speech" for f in kept),
        "kept_deny": sum(f["polarity"] == "deny" for f in kept),
        "kept_with_day_text": sum(bool(f["day_text"]) for f in kept),
        "kept_with_context": sum(bool(f["context"]) for f in kept),
        "quote_grounding": g,
        "sec_per_chunk_live": round(sum(r.wall_s for r in live) / len(live), 1) if live else None,
    }


def select_chunks(path: Path, stories: Sequence[str] | None, limit: int) -> list[dict]:
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if not stories or rec.get("story") in stories:
                    recs.append(rec)
    return recs[:limit] if limit else recs


def main(argv: Sequence[str] | None = None, client: LLMClient | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m detective_board.extract.presence")
    ap.add_argument("--model", required=True)
    ap.add_argument("--chunks", type=Path, required=True)
    ap.add_argument("--story", action="append", help="only this story (repeatable)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cache", type=Path, default=Path("data/cache/presence-cache.sqlite"))
    ap.add_argument("--graph-db", type=Path, help="ingest the facts into this graph DB")
    ap.add_argument("--out", type=Path, help="write one result record per chunk (jsonl)")
    ap.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--num-ctx", type=int, default=4096)
    ap.add_argument("--num-predict", type=int, default=768)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fuzzy-threshold", type=float, default=0.85)
    ap.add_argument(
        "--lenient", action="store_true", help="keep values not found in the quote (LOW)"
    )
    ap.add_argument("--no-normalise", action="store_true", help="do not run the normaliser")
    a = ap.parse_args(argv)

    cfg = PresenceConfig(
        a.model, a.num_ctx, a.num_predict, a.seed,
        fuzzy_threshold=a.fuzzy_threshold, lenient=a.lenient,
    )  # fmt: skip
    cache = ExtractCache(a.cache)
    ex = PresenceExtractor(client or OllamaClient(a.host), cfg, cache, load_prompt(a.prompt))
    recs = select_chunks(a.chunks, a.story, a.limit)
    store = None
    known_by_story: dict[str, KnownEntities] = {}
    if a.graph_db:
        from detective_board.graph import GraphStore

        a.graph_db.parent.mkdir(parents=True, exist_ok=True)
        store = GraphStore(str(a.graph_db))
    results: list[PresenceResult] = []
    t0 = time.perf_counter()
    out = open(a.out, "w", encoding="utf-8") if a.out else None  # noqa: SIM115
    if out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        for i, rec in enumerate(recs, 1):
            story = rec.get("story", "")
            if store is not None and story not in known_by_story:
                known_by_story[story] = known_from_graph(store, story)
            r = ex.extract_chunk(rec["chunk_id"], story, rec["text"], known_by_story.get(story))
            results.append(r)
            if out:
                out.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
                out.flush()
            tag = "cache" if r.cached else f"{r.wall_s:.0f}s"
            print(f"[{i}/{len(recs)}] {r.chunk_id} {r.status} {tag} facts={len(r.facts)}"
                  f"{' TRUNC' if r.truncated else ''}", file=sys.stderr)  # fmt: skip
    finally:
        if out:
            out.close()
        cache.close()
    report = build_report(results)
    report.update(
        model=a.model, prompt_version=ex.prompt.version, schema_version=SCHEMA_VERSION,
        lenient=a.lenient, total_s=round(time.perf_counter() - t0, 1),
    )  # fmt: skip
    if store is not None:
        from detective_board.extract import normalise as normaliser
        from detective_board.graph import ChunkRef

        by_id = {r["chunk_id"]: r for r in recs}
        n_ing = 0
        for r in results:
            if r.status in ("ok", "repaired"):
                rep = store.ingest_presence(
                    ChunkRef.from_record(by_id[r.chunk_id]), r.grounded_facts()
                )
                n_ing += rep.events + rep.claims
        report["graph_nodes_ingested"] = n_ing
        if not a.no_normalise:
            for story in sorted({r.story for r in results}):
                normaliser.apply(store, story)
        store.close()
    print("== report", file=sys.stderr)
    for k, v in report.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
