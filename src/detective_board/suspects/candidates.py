"""Candidates for 'who is responsible' from the graph: persons mentioned before the cut.

Deterministic. Holmes, Watson, role words and the victim named in the question are dropped; a bare
surname or first name is merged into the single multi-word node that shares it; at most `cap`
candidates by mention count. `NO_PERSON` (accident, animal, suicide) is always offered. Names can be
masked as `Person-A`, `Person-B` ... so a model cannot answer from memory of the story.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from detective_board.suspects import NO_PERSON

TITLES = {"mr", "mrs", "miss", "dr", "sir", "lady", "captain", "colonel", "inspector", "lord",
          "professor", "major", "squire", "master", "madam", "mme", "rev", "reverend"}  # fmt: skip
STOP_SINGLE = {"witness", "narrator", "father", "mother", "coroner", "inspector", "doctor",
               "sergeant", "constable", "gentleman", "lady", "master", "sir", "madam", "stranger",
               "servant", "maid", "clerk", "friend", "man", "woman", "boy", "girl", "police"}  # fmt: skip
DETECTIVES = {"holmes", "sherlock holmes", "mr. sherlock holmes", "mr. holmes", "watson",
              "dr. watson", "john watson"}  # fmt: skip
_WORD = re.compile(r"[A-Za-z][A-Za-z.'’-]*")


def _tokens(name: str) -> list[str]:
    return [t.strip(".").lower() for t in _WORD.findall(name)]


def _core(name: str) -> list[str]:
    return [t for t in _tokens(name) if t not in TITLES]


@dataclass
class Candidate:
    key: str  # stable id, 'c0', 'c1', ...
    name: str  # display name
    surfaces: set[str] = field(default_factory=set)  # every written form (for matching and masking)
    mentions: int = 0
    label: str = ""  # what the model sees: the name, or Person-X when masked

    def matches(self, text: str) -> bool:
        low = text.lower()
        return any(re.search(rf"\b{re.escape(s.lower())}\b", low) for s in self.surfaces)


def _bad_name(name: str) -> bool:
    if "’s" in name or "'s" in name:
        return True
    toks = _core(name)
    if not toks or (len(toks) == 1 and toks[0] in STOP_SINGLE):
        return True
    return any(t in {"the", "of", "and", "a", "an", "his", "her"} for t in toks[:1])


def build_candidates(
    db: sqlite3.Connection, story: str, cut_char: int, question: str = "", *, cap: int = 12
) -> list[Candidate]:
    rows = db.execute(
        """select n.id, n.name, m.surface, count(*) from g_node n
           join g_mention m on m.node_id = n.id join g_chunk c on c.chunk_id = m.chunk_id
           where n.kind = 'person' and n.unnamed = 0 and n.story = ?
             and m.role in ('name','alias') and c.char_end <= ?
           group by n.id, m.surface""",
        (story, cut_char),
    ).fetchall()
    nodes: dict[str, Candidate] = {}
    for node_id, name, surface, cnt in rows:
        if not name or _bad_name(name) or " ".join(_core(name)) in DETECTIVES:
            continue
        if " ".join(_tokens(name)) in DETECTIVES:
            continue
        cand = nodes.setdefault(node_id, Candidate(node_id, name))
        cand.surfaces.add(surface)
        cand.surfaces.add(name)
        cand.mentions += cnt
    cands = _merge_partial_names(list(nodes.values()))
    q = set(_core(question))
    kept = []
    for c in cands:
        core = _core(c.name)
        if q and core and set(core) <= q and len(core) <= len(q):
            continue  # the victim named in the question (or a bare surname of the victim)
        kept.append(c)
    kept.sort(key=lambda c: (-c.mentions, c.name))
    kept = kept[:cap]
    for i, c in enumerate(kept):
        c.key = f"c{i}"
        c.label = c.name
        c.surfaces |= {s for s in (_stripped(x) for x in c.surfaces) if s}
    return kept


def _stripped(surface: str) -> str:
    toks = [
        t
        for t in re.findall(r"[A-Za-z][A-Za-z.'’-]*", surface)
        if t.strip(".").lower() not in TITLES
    ]
    return " ".join(toks) if toks and len(" ".join(toks)) >= 3 else ""


def _merge_partial_names(cands: list[Candidate]) -> list[Candidate]:
    """A single-token node merges into the one multi-word node containing that token."""
    multi = [c for c in cands if len(_core(c.name)) >= 2]
    out: list[Candidate] = list(multi)
    for c in cands:
        core = _core(c.name)
        if len(core) >= 2:
            continue
        hits = [m for m in multi if core and core[0] in _core(m.name)]
        if len(hits) == 1:
            hits[0].mentions += c.mentions
            hits[0].surfaces |= c.surfaces
        else:
            out.append(c)
    # two nodes with the same normalised name (Turner / Mr. John Turner already merged above)
    seen: dict[str, Candidate] = {}
    for c in out:
        k = " ".join(_core(c.name))
        if k in seen:
            seen[k].mentions += c.mentions
            seen[k].surfaces |= c.surfaces
        else:
            seen[k] = c
    return list(seen.values())


def mask_candidates(cands: list[Candidate]) -> None:
    """Set `label` to Person-A, Person-B ... (in place)."""
    for i, c in enumerate(cands):
        c.label = f"Person-{chr(ord('A') + i)}"


def mask_text(text: str, cands: Sequence[Candidate]) -> str:
    """Replace every surface form of every candidate by its label (longest form first)."""
    pairs = sorted(((s, c.label) for c in cands for s in c.surfaces if len(s) >= 3),
                   key=lambda p: -len(p[0]))  # fmt: skip
    if not pairs:
        return text
    pat = re.compile(r"\b(" + "|".join(re.escape(s) for s, _ in pairs) + r")\b")
    lab = {s: label for s, label in pairs}
    return pat.sub(lambda m: lab[m.group(1)], text)


def labels(cands: Sequence[Candidate]) -> list[str]:
    return [c.label for c in cands] + [NO_PERSON]
