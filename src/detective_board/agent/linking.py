"""Entity linking for rule-tool arguments (backlog R-12): question names -> graph person ids.

Exact normalised name or alias only (GraphStore.resolve: case, titles and possessives ignored;
no fuzzy match). Ambiguity is reported with its candidates, never resolved by guessing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from detective_board.graph.normalize import normalize_name

LinkStatus = Literal["ok", "ambiguous", "not_found", "no_names"]


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    story: str


@dataclass(frozen=True)
class Link:
    status: LinkStatus
    mention: str | None = None
    person_id: str | None = None
    story: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    reason: str = ""
    matched: str | None = None  # the surface form that was looked up (mention or its surname)

    def note(self) -> str:
        """One line for the trace and the prompt header."""
        if self.status == "ambiguous":
            names = ", ".join(f"{c.name} ({c.story})" for c in self.candidates)
            return f"name {self.mention!r} is ambiguous: {names}; no person was chosen"
        return self.reason


def _candidates(graph: Any, name: str, story: str | None) -> list[Candidate]:
    res = graph.find_entities(name, kind="person", story=story)
    by_id = {n.id: n for n in res.nodes}
    out = []
    for nid in res.seeds:
        n = by_id.get(nid)
        if n is not None and n.kind == "person":
            out.append(Candidate(nid, n.name or n.label, n.story))
    return out


def _same_given_names(mention: str, cand: Candidate) -> bool:
    """Surname fallback: 'Aloysius Garcia' may be 'Garcia', never 'John Garcia'."""
    known = normalize_name(cand.name).split()
    return len(known) == 1 or known[:-1] == normalize_name(mention).split()[:-1]


def link_person(graph: Any, names: Sequence[str], stories: Sequence[str] = ()) -> Link:
    """The first question name that resolves to exactly one person, in the story the retrieval
    ranks highest among the candidates' stories (`stories`: retrieval order). A name with
    several persons in that story, or persons in several stories none of which was retrieved,
    is `ambiguous`; other names are not tried after an ambiguous one."""
    if not names:
        return Link("no_names", reason="no person name in the question")
    tried: list[str] = []
    for name in names:
        matched, how = name, "exact name/alias"
        cands = _candidates(graph, name, None)
        if not cands and len(name.split()) > 1:  # "Aloysius Garcia" when only "Garcia" is known
            matched, how = name.split()[-1], f"surname {name.split()[-1]!r}"
            cands = [c for c in _candidates(graph, matched, None) if _same_given_names(name, c)]
        if not cands:
            tried.append(name)
            continue
        cand_stories = sorted({c.story for c in cands})
        story = next((s for s in stories if s in cand_stories), None)
        if story is None and len(cand_stories) == 1:
            story = cand_stories[0]
        pool = [c for c in cands if c.story == story] if story else cands
        if len(pool) == 1:
            c = pool[0]
            why = f"{name!r} -> {c.id} ({how} in {c.story})"
            return Link("ok", name, c.id, c.story, pool, why, matched)
        pool = sorted(pool, key=lambda c: c.id)
        return Link("ambiguous", name, None, story, pool, matched=matched)
    return Link("not_found", None, reason=f"no person in the graph named {', '.join(tried)}")
