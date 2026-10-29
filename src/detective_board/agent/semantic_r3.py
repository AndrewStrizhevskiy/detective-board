"""Neuro-symbolic R3: the graph finds candidate pairs of statements about the same thing from
different speakers; a small model judges each pair from the two verbatim quotes only.

The model's verdict is never a rule verdict. It is shown as a `hypothesis` (label `conditional`),
with both quotes, in a block that is separate from the rule result, and it is worded as "judged by
a small model, not proven". An empty block never means that the accounts agree.

Pairing is deterministic and uses no model: claims (and narrator events) of one story are paired
when different speakers' quotes share content words (story-wide common words weigh less) and
entity names; pairs are ranked by that score and capped.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .llm import LLM
from .rule_first import RuleAnswer, _Cites
from .window import content_words

JUDGE_VERSION = "R3J-2"
VERDICTS = ("contradicts", "consistent", "unrelated")
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}},
    "required": ["verdict"],
}
# One static prefix: identical for every pair, so the server can reuse its prefill.
JUDGE_SYSTEM_PROMPT = (
    "You compare two statements taken from a detective story. Each statement is quoted "
    "word for word with the name of the person who says it. Answer with exactly one word.\n"
    "contradicts: both statements make a claim about the SAME event, person or object, and one "
    "specific fact (place, time, order, number, identity, cause, or a denial) cannot be true in "
    "both. Different opinions, guesses, plans, feelings or different moments of the story are "
    "NOT a contradiction.\n"
    "consistent: same subject and both can be true.\n"
    "unrelated: different subjects, or one statement is vague or states nothing checkable.\n"
    "When in doubt, answer unrelated. Judge only from the two quotes; use no outside knowledge.\n"
    'Example. A (Mary): "I was at the station at nine." B (John): "Mary was in the garden '
    'at nine." Answer: contradicts.\n'
    'Example. A (Mary): "I left the house early." B (John): "The garden was full of '
    'roses." Answer: unrelated.'
)
JUDGE_QUESTION = "Do these two statements contradict each other?"

MIN_SHARED_WORDS = 2
MIN_QUOTE_WORDS = 3
MAX_QUOTE_CHARS = 400


@dataclass(frozen=True)
class Statement:
    id: str
    speaker: str  # display name; "narrator" for narrator events
    speaker_id: str  # node id of the speaker; "narrator" for narrator events
    quote: str
    chunk_id: str
    story: str
    char_start: int
    char_end: int
    kind: str  # claim | narrator


@dataclass(frozen=True)
class Pair:
    a: Statement
    b: Statement
    score: float
    shared: tuple[str, ...] = ()


@dataclass(frozen=True)
class Judged:
    pair: Pair
    verdict: str | None  # one of VERDICTS, or None when the model's answer was unusable
    raw: str = ""


# ----------------------------------------------------------------------------- candidates
def load_statements(conn: Any, story: str) -> list[Statement]:
    """Claims with a speaker and an anchored quote, plus narrator-voice events, of one story.
    Read-only; deterministic order (by id)."""
    out: list[Statement] = []
    rows = conn.execute(
        "SELECT n.id, n.quote, n.chunk_id, n.char_start, n.char_end, p.id AS sid, p.name AS sname "
        "FROM g_node n JOIN g_edge e ON e.dst = n.id AND e.rel = 'ASSERTS' "
        "JOIN g_node p ON p.id = e.src "
        "WHERE n.kind = 'claim' AND n.story = ? AND n.quote IS NOT NULL "
        "AND n.chunk_id IS NOT NULL ORDER BY n.id",
        (story,),
    ).fetchall()
    for r in rows:
        out.append(
            Statement(
                r["id"],
                r["sname"] or r["sid"],
                r["sid"],
                " ".join(r["quote"].split()),
                r["chunk_id"],
                story,
                r["char_start"] or 0,
                r["char_end"] or 0,
                "claim",
            )
        )
    for r in conn.execute(
        "SELECT id, quote, chunk_id, char_start, char_end, props_json FROM g_node "
        "WHERE kind = 'event' AND story = ? AND quote IS NOT NULL AND chunk_id IS NOT NULL "
        "ORDER BY id",
        (story,),
    ):
        try:
            narrator = bool(json.loads(r["props_json"]).get("narrator"))
        except (ValueError, TypeError):
            narrator = False
        if narrator:
            out.append(
                Statement(
                    r["id"],
                    "narrator",
                    "narrator",
                    " ".join(r["quote"].split()),
                    r["chunk_id"],
                    story,
                    r["char_start"] or 0,
                    r["char_end"] or 0,
                    "narrator",
                )
            )
    return out


def entity_names(conn: Any, story: str) -> set[str]:
    """Lower-cased names of the persons, places and items of the story (whole words only)."""
    rows = conn.execute(
        "SELECT name FROM g_node WHERE story = ? AND kind IN ('person','place','item') "
        "AND name IS NOT NULL",
        (story,),
    )
    return {" ".join(r["name"].lower().split()) for r in rows if len(r["name"]) >= 4}


def person_terms(conn: Any, person_ids: Sequence[str]) -> set[str]:
    """Lower-cased full names and surnames (>= 4 letters), to find statements about persons."""
    terms: set[str] = set()
    for pid in person_ids:
        r = conn.execute("SELECT name FROM g_node WHERE id = ?", (pid,)).fetchone()
        if r and r["name"]:
            name = " ".join(r["name"].lower().split())
            terms.add(name)
            last = name.split()[-1]
            if len(last) >= 4:
                terms.add(last)
    return terms


def candidate_pairs(
    statements: Sequence[Statement],
    *,
    persons: Sequence[str] = (),
    person_names: set[str] | None = None,
    entities: set[str] | None = None,
    max_pairs: int = 12,
) -> list[Pair]:
    """Pairs of statements by different speakers about the same thing, best first.

    score = sum of the weights of the shared content words (ln(N/df) over the story's
    statements) + 1.5 per shared entity name. A pair needs >= MIN_SHARED_WORDS shared words. With
    `persons` (graph node ids; `person_names` their name forms) at least one side must be asserted
    by one of them or mention one of the names. Ties are broken
    by statement ids, so the list is deterministic."""
    sts = [s for s in statements if len(content_words(s.quote)) >= MIN_QUOTE_WORDS]
    words = [content_words(s.quote) for s in sts]
    df: Counter[str] = Counter()
    for w in words:
        df.update(w)
    n = max(len(sts), 1)
    weight = {w: math.log(1 + n / c) for w, c in df.items()}
    lowered = [s.quote.lower() for s in sts]
    ents = entities or set()
    named = [{e for e in ents if re.search(rf"\b{re.escape(e)}\b", q)} for q in lowered]
    who = set(persons)
    names = person_names or set()
    about = [
        bool(names) and any(re.search(rf"\b{re.escape(t)}\b", q) for t in names) for q in lowered
    ]
    pairs: list[Pair] = []
    for i in range(len(sts)):
        for j in range(i + 1, len(sts)):
            a, b = sts[i], sts[j]
            if a.speaker_id == b.speaker_id or (a.kind == b.kind == "narrator"):
                continue
            if (who or names) and not (
                a.speaker_id in who or b.speaker_id in who or about[i] or about[j]
            ):
                continue
            if a.chunk_id == b.chunk_id and a.char_start == b.char_start:
                continue
            shared = words[i] & words[j]
            if len(shared) < MIN_SHARED_WORDS:
                continue
            common_ents = named[i] & named[j]
            score = sum(weight[w] for w in shared) + 1.5 * len(common_ents)
            first, second = sorted((a, b), key=lambda s: s.id)
            pairs.append(Pair(first, second, round(score, 6), tuple(sorted(shared))))
    pairs.sort(key=lambda p: (-p.score, p.a.id, p.b.id))
    return pairs[:max_pairs]


# ----------------------------------------------------------------------------- judge
def _clip(q: str) -> str:
    return q if len(q) <= MAX_QUOTE_CHARS else q[:MAX_QUOTE_CHARS].rsplit(" ", 1)[0]


def judge_messages(pair: Pair) -> list[dict[str, str]]:
    """The static system prompt, then the two quotes: only the user part differs between pairs."""
    user = (
        f'Statement A, said by {pair.a.speaker}: "{_clip(pair.a.quote)}"\n'
        f'Statement B, said by {pair.b.speaker}: "{_clip(pair.b.quote)}"\n'
        f"{JUDGE_QUESTION}"
    )
    return [{"role": "system", "content": JUDGE_SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_verdict(text: str) -> str | None:
    """The enum value of the model's JSON answer; None for anything else (invalid, empty)."""
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    v = obj.get("verdict") if isinstance(obj, dict) else None
    return v if isinstance(v, str) and v in VERDICTS else None


def judge_pair(llm: LLM, pair: Pair, *, seed: int = 42) -> Judged:
    raw = "".join(
        llm.chat(
            judge_messages(pair),
            temperature=0.0,
            seed=seed,
            format=JUDGE_SCHEMA,
            num_predict=24,
        )
    )
    return Judged(pair, parse_verdict(raw), raw)


def judge_pairs(
    llm: LLM, pairs: Sequence[Pair], *, on_each: Callable[[Judged], None] | None = None
) -> list[Judged]:
    out = []
    for p in pairs:
        try:
            j = judge_pair(llm, p)
        except Exception as exc:  # noqa: BLE001 - one slow or failed call must not end a run
            j = Judged(p, None, f"error: {type(exc).__name__}")
        out.append(j)
        if on_each:
            on_each(j)
    return out


@dataclass
class Outcome:
    """What the second block rests on."""

    judged: list[Judged] = field(default_factory=list)
    error: str = ""

    @property
    def contradicting(self) -> list[Judged]:
        return [j for j in self.judged if j.verdict == "contradicts"]


def find_candidates(
    llm: LLM,
    conn: Any,
    story: str,
    *,
    persons: Sequence[str] = (),
    max_pairs: int = 12,
) -> Outcome:
    """Pairing (no model) then one judge call per pair. Model failures become `error`."""
    try:
        pairs = candidate_pairs(
            load_statements(conn, story),
            persons=persons,
            person_names=person_terms(conn, persons),
            entities=entity_names(conn, story),
            max_pairs=max_pairs,
        )
    except Exception as exc:  # noqa: BLE001 - a graph problem must not break the answer
        return Outcome(error=f"candidate search failed ({type(exc).__name__})")
    out = Outcome()
    for p in pairs:
        try:
            out.judged.append(judge_pair(llm, p))
        except Exception as exc:  # noqa: BLE001 - the local model may be down or slow
            out.error = f"the model could not be reached ({type(exc).__name__})"
            break
    return out


# ----------------------------------------------------------------------------- the answer block
BLOCK_TITLE = "Model-judged candidates (hypotheses, not rule findings)"
NOT_PROVEN = "judged by a small model, not proven"


def render_block(
    out: Outcome, answer: RuleAnswer, *, show: int = 2, min_quote_chars: int = 6
) -> RuleAnswer:
    """The answer with the separate hypotheses block appended (a new RuleAnswer). The block is
    always present when the switch is on, so an empty one cannot be read as agreement."""
    c = _Cites.resume(answer.sources, min_quote_chars)
    lines = [
        f"{BLOCK_TITLE}: label hypothesis (conditional), {NOT_PROVEN}. "
        f"These are not output of rules R1-R3 ({JUDGE_VERSION})."
    ]
    shown = 0
    for j in out.contradicting:
        if shown >= show:
            break
        cites = []
        for st in (j.pair.a, j.pair.b):
            anchor = {
                "chunk_id": st.chunk_id,
                "story": st.story,
                "char_start": st.char_start,
                "char_end": st.char_end,
                "quote": st.quote,
            }
            cites.append(
                c.add(
                    anchor,
                    "conditional",
                    origin="graph",
                    summary=f"hypothesis ({NOT_PROVEN})",
                )
            )
        if not all(cites):
            continue
        shown += 1
        lines.append(
            f"- Hypothesis {shown} ({NOT_PROVEN}): the model judged that "
            f"{j.pair.a.speaker} {cites[0]} and {j.pair.b.speaker} {cites[1]} may contradict "
            "each other. Read both quotes yourself."
        )
    n = len(out.judged)
    if out.error and not shown:
        lines.append(
            f"- The model check did not complete: {out.error}. "
            f"{n} pair{'s' if n != 1 else ''} judged before that."
        )
    elif not shown:
        lines.append(
            f"- {n} candidate pair{'s' if n != 1 else ''} judged; none was judged as "
            "contradicting. This does not show that the accounts are consistent."
        )
    else:
        rest = len(out.contradicting) - shown
        more = f" ({rest} more judged the same way)" if rest > 0 else ""
        lines.append(
            f"Pairs judged: {n}{more}. A judgement by the model can be wrong in both directions."
        )
    return RuleAnswer(answer.text + "\n" + "\n".join(lines), c.sources, answer.kind)
