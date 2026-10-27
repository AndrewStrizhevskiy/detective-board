"""Verification and self-consistency voting for the presence pass (docs/symbolic-layer.md 11.3).

Both steps work on `GroundedFact`s, i.e. after the deterministic grounding of `presence.py`:

 - `PresenceVerifier`: one tiny LLM call per kept fact. The model sees the verbatim quote, the
   sentence before and after it (from the chunk) and the claim "PERSON was at PLACE at TIME" and
   answers a closed JSON schema: person_ok / place_ok / time_ok in {yes, no} and verdict in
   {yes, partly, no}. A selection task, so a 4B model should do it; QUALITY IS UNMEASURED.
   Decision (`decide`, no LLM): `yes` keeps the fact; `no`, an unparseable answer, an error or a
   wrong person (`person_ok == no`) rejects it (reason VERIFY_REJECTED + the field verdicts);
   `partly` rejects unless `accept_partly`, which keeps it with every failing field (place/time)
   moved into `GroundedFact.context` (so LOW downstream, a time is not written to the event, the
   place edge is weak) and the code VERIFY_PARTLY. A person is never nulled: a fact about nobody is
   no fact. Wording lives in `prompts/extract/presence_verify_v1.txt` (versioned, replaceable).
   Cache: the same SQLite file as the extraction, key prefix `verify:` + sha256 over the sentence
   context, claim, verifier model, prompt version, schema version and options.

 - `vote`: with `--samples N` the presence call is run N times (seeds seed+k, small temperature);
   a fact is kept when at least N//2 + 1 samples produced it. Agreement = same polarity, same
   normalised person, place and time_text, and overlapping quotes (>= 50% of the shorter span).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from detective_board.extract.cache import ExtractCache, cache_key
from detective_board.extract.llm import GenRequest, LLMClient
from detective_board.extract.pipeline import PROMPT_DIR
from detective_board.extract.presence_schema import GroundedFact
from detective_board.graph.normalize import fold_text, normalize_name

VERIFY_SCHEMA_VERSION = "presence-verify-1"
VERIFY_PROMPT = PROMPT_DIR / "presence_verify_v1.txt"
VERIFY_KEY_PREFIX = "verify:"
REJECTED = "VERIFY_REJECTED"
PARTLY_CODE = "VERIFY_PARTLY"
MAX_CONTEXT_CHARS = 400
REQUIRED_MARKS = ("{{QUOTE}}", "{{CLAIM}}")
MARKS = (
    "{{PREVIOUS}}",
    "{{QUOTE}}",
    "{{NEXT}}",
    "{{CLAIM}}",
    "{{PERSON}}",
    "{{PLACE}}",
    "{{TIME}}",
)
YES_NO = ("yes", "no")
VERDICTS = ("yes", "partly", "no")


# --------------------------------------------------------------------------- prompt and schema


@dataclass(frozen=True)
class VerifyPrompt:
    version: str
    template: str

    def render(self, **fields: str) -> str:
        out = self.template
        for mark in MARKS:
            out = out.replace(mark, fields.get(mark.strip("{}").lower(), ""))
        return out


def load_verify_prompt(path: str | Path = VERIFY_PROMPT) -> VerifyPrompt:
    head, sep, body = Path(path).read_text(encoding="utf-8").partition("\n---\n")
    if not sep or not head.startswith("version:"):
        raise ValueError(f"{path}: expected 'version: X' header followed by '---'")
    for mark in REQUIRED_MARKS:
        if mark not in body:
            raise ValueError(f"{path}: template lacks {mark}")
    return VerifyPrompt(head.split(":", 1)[1].strip(), body)


def verify_schema() -> dict:
    """The closed answer schema (Ollama `format`): four enums, all required, nothing else."""
    yn = {"type": "string", "enum": list(YES_NO)}
    return {
        "type": "object",
        "properties": {
            "person_ok": yn,
            "place_ok": yn,
            "time_ok": yn,
            "verdict": {"type": "string", "enum": list(VERDICTS)},
        },
        "required": ["person_ok", "place_ok", "time_ok", "verdict"],
        "additionalProperties": False,
    }


# --------------------------------------------------------------------------- sentence context

_BREAK = re.compile(r"[.!?]+[’”\"')\]]*(?=\s+[A-Z‘“\"'(]|\s*$)")
_ABBREV = frozenset("mr mrs ms dr st messrs mme capt col gen sir hon rev prof jr sr".split())


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of the sentences of `text`; abbreviations such as 'Mr.' do not end one."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BREAK.finditer(text):
        word = re.search(r"(\w+)\W*$", text[start : m.start()])
        if m.group().startswith(".") and word and word.group(1).casefold() in _ABBREV:
            continue
        spans.append((start, m.end()))
        start = m.end()
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


def context_sentences(chunk_text: str, quote: str) -> tuple[str, str]:
    """The sentence before and the sentence after the one(s) the quote lies in ('' if none)."""
    i = chunk_text.find(quote)
    if i < 0 or not quote:
        return "", ""
    j = i + len(quote)
    spans = sentence_spans(chunk_text)
    first = next((k for k, (_, e) in enumerate(spans) if e > i), None)
    last = next((k for k in range(len(spans) - 1, -1, -1) if spans[k][0] < j), None)
    if first is None or last is None:
        return "", ""
    prev = chunk_text[slice(*spans[first - 1])].strip() if first > 0 else ""
    nxt = chunk_text[slice(*spans[last + 1])].strip() if last + 1 < len(spans) else ""
    return prev[-MAX_CONTEXT_CHARS:], nxt[:MAX_CONTEXT_CHARS]


def claim_text(f: GroundedFact) -> str:
    verb = "was NOT at" if f.polarity == "deny" else "was at"
    return f"{f.person} {verb} {f.place} at {f.time_text}"


# --------------------------------------------------------------------------- verifier


@dataclass(frozen=True)
class VerifyConfig:
    model: str
    num_ctx: int = 2048
    num_predict: int = 64  # the answer is about 25 tokens
    seed: int = 42
    temperature: float = 0.0
    accept_partly: bool = False  # keep 'partly' with the failing field(s) nulled (LOW)

    def options(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
        }


@dataclass
class VerifyAnswer:
    status: str  # ok | unparseable | error
    verdict: str | None = None
    person_ok: str | None = None
    place_ok: str | None = None
    time_ok: str | None = None
    cached: bool = False
    error: str | None = None
    wall_s: float = 0.0

    def fields(self) -> dict[str, str | None]:
        return {"person_ok": self.person_ok, "place_ok": self.place_ok, "time_ok": self.time_ok}


@dataclass
class Decision:
    accepted: bool
    # yes | partly_accepted | no | partly | person_no | partly_no_field | unparseable | error
    detail: str
    nulled: list[str] = field(default_factory=list)  # context fields (place / time_text)


def parse_answer(text: str) -> tuple[dict[str, str] | None, str | None]:
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return None, "not JSON"
    if not isinstance(d, dict):
        return None, "not an object"
    out: dict[str, str] = {}
    for k, allowed in (
        ("person_ok", YES_NO),
        ("place_ok", YES_NO),
        ("time_ok", YES_NO),
        ("verdict", VERDICTS),
    ):
        v = d.get(k)
        if not isinstance(v, str) or v not in allowed:
            return None, f"bad {k}: {v!r}"
        out[k] = v
    return out, None


def decide(a: VerifyAnswer, accept_partly: bool) -> Decision:
    """Pure function: the keep/reject rule (see the module doc)."""
    if a.status == "error":
        return Decision(False, "error")
    if a.status != "ok":
        return Decision(False, "unparseable")
    if a.person_ok == "no":
        return Decision(False, "person_no")
    if a.verdict == "no":
        return Decision(False, "no")
    failing = [name for name, v in (("place", a.place_ok), ("time_text", a.time_ok)) if v == "no"]
    if a.verdict == "yes" and not failing:
        return Decision(True, "yes")
    # 'partly', or a 'yes' that contradicts its own field verdicts (treated as partly)
    if not accept_partly:
        return Decision(False, "partly")
    if not failing:
        return Decision(False, "partly_no_field")
    return Decision(True, "partly_accepted", failing)


class PresenceVerifier:
    def __init__(
        self,
        client: LLMClient,
        cfg: VerifyConfig,
        cache: ExtractCache | None = None,
        prompt: VerifyPrompt | None = None,
    ) -> None:
        self.client = client
        self.cfg = cfg
        self.cache = cache
        self.prompt = prompt or load_verify_prompt()
        self._schema = verify_schema()

    def _fields(self, chunk_text: str, f: GroundedFact) -> dict[str, str]:
        prev, nxt = context_sentences(chunk_text, f.quote)
        return {
            "previous": prev or "(none)",
            "quote": f.quote,
            "next": nxt or "(none)",
            "claim": claim_text(f),
            "person": f.person,
            "place": f.place,
            "time": f.time_text,
        }

    def key(self, chunk_text: str, f: GroundedFact) -> str:
        """Verifier model, prompt version, schema version, options and the rendered prompt (all the
        model sees) are in the key; the prefix keeps it apart from extraction keys."""
        rendered = self.prompt.render(**self._fields(chunk_text, f))
        return VERIFY_KEY_PREFIX + cache_key(
            rendered,
            self.cfg.model,
            self.prompt.version,
            VERIFY_SCHEMA_VERSION,
            self.cfg.options(),
        )

    def verify(self, chunk_text: str, f: GroundedFact) -> VerifyAnswer:
        key = self.key(chunk_text, f)
        rec = self.cache.get(key) if self.cache is not None else None
        cached = rec is not None
        if rec is None:
            req = GenRequest(
                self.cfg.model,
                self.prompt.render(**self._fields(chunk_text, f)),
                self._schema,
                self.cfg.options(),
            )
            try:
                r = self.client.generate(req)
            except Exception as e:  # not cached: a rerun asks again
                return VerifyAnswer("error", error=f"{type(e).__name__}: {str(e)[:200]}")
            rec = {"text": r.text, "done_reason": r.done_reason, "wall_s": r.wall_s}
            if self.cache is not None:
                self.cache.put(key, rec)
        parsed, err = parse_answer(rec["text"])
        wall = float(rec.get("wall_s") or 0.0)
        if parsed is None:
            return VerifyAnswer("unparseable", error=err, cached=cached, wall_s=wall)
        return VerifyAnswer("ok", cached=cached, wall_s=wall, **parsed)

    def apply(self, chunk_text: str, f: GroundedFact) -> tuple[GroundedFact | None, dict[str, Any]]:
        """(the fact with its verification record or None if rejected, the record)."""
        a = self.verify(chunk_text, f)
        d = decide(a, self.cfg.accept_partly)
        record: dict[str, Any] = {
            "verdict": a.verdict, **a.fields(), "status": a.status, "detail": d.detail,
            "prompt_version": self.prompt.version, "model": self.cfg.model,
            "nulled": d.nulled, "cached": a.cached,
        }  # fmt: skip
        if a.error:
            record["error"] = a.error
        if not d.accepted:
            return None, record
        context = list(dict.fromkeys([*f.context, *d.nulled]))
        codes = [*f.codes, PARTLY_CODE] if d.nulled else list(f.codes)
        stored = {k: v for k, v in record.items() if k != "cached"}  # keeps reruns identical
        return f.model_copy(update={"verify": stored, "context": context, "codes": codes}), record


# --------------------------------------------------------------------------- voting


def vote_key(f: GroundedFact) -> tuple[str, str, str, str]:
    return (
        fold_text(normalize_name(f.person)) or fold_text(f.person),
        fold_text(f.place),
        fold_text(f.time_text),
        f.polarity,
    )


def _span(chunk_text: str, quote: str) -> tuple[int, int]:
    i = chunk_text.find(quote)
    return (i, i + len(quote)) if i >= 0 else (-1, -1)


def quotes_overlap(chunk_text: str, a: str, b: str) -> bool:
    sa, sb = _span(chunk_text, a), _span(chunk_text, b)
    if sa[0] < 0 or sb[0] < 0:
        return fold_text(a) == fold_text(b)
    ov = max(0, min(sa[1], sb[1]) - max(sa[0], sb[0]))
    return ov >= 0.5 * min(sa[1] - sa[0], sb[1] - sb[0])


def needed_votes(n_samples: int) -> int:
    """Strict majority: floor(N/2) + 1 (1 of 1, 2 of 2, 2 of 3, 3 of 4, 3 of 5)."""
    return n_samples // 2 + 1


@dataclass
class VoteOutcome:
    kept: list[GroundedFact] = field(default_factory=list)
    below: list[tuple[GroundedFact, int]] = field(default_factory=list)  # (fact, votes)
    clusters: int = 0


def vote(
    samples: Sequence[Sequence[GroundedFact]], chunk_text: str, n_samples: int | None = None
) -> VoteOutcome:
    """Majority vote over per-sample grounded facts. `n_samples` (default len(samples)) is the
    number of samples ASKED for: a sample that failed counts as a vote for nothing. A fact counts
    once per sample. The kept fact is the first sample's version, with `votes` and `samples` set."""
    n = n_samples if n_samples is not None else len(samples)
    clusters: list[dict[str, Any]] = []  # {"fact", "key", "samples": set[int]}
    for si, facts in enumerate(samples):
        for f in facts:
            k = vote_key(f)
            for c in clusters:
                if c["key"] == k and quotes_overlap(chunk_text, c["fact"].quote, f.quote):
                    c["samples"].add(si)  # a repeat within one sample is still one vote
                    break
            else:
                clusters.append({"fact": f, "key": k, "samples": {si}})
    out = VoteOutcome(clusters=len(clusters))
    need = needed_votes(n)
    for c in clusters:
        votes = len(c["samples"])
        if votes >= need:
            out.kept.append(c["fact"].model_copy(update={"votes": votes, "samples": n}))
        else:
            out.below.append((c["fact"], votes))
    return out
