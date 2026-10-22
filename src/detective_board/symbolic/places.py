"""Place resolution and PlaceRel (spec section 5): exact normalised match only."""

from __future__ import annotations

from enum import StrEnum

from detective_board.symbolic.facts import PlaceRec


class PlaceRel(StrEnum):
    SAME = "SAME"
    CONTAINS = "CONTAINS"
    DISTINCT = "DISTINCT"
    UNKNOWN = "UNKNOWN"


def normalize(s: str) -> str:
    out = " ".join(s.lower().split())
    return out.removeprefix("the ").strip()


class PlaceIndex:
    def __init__(self, places: list[PlaceRec]) -> None:
        self._by_id = {p.id: p for p in places}
        alias: dict[str, set[str]] = {}
        for p in places:
            for name in (p.name, *p.aliases):
                alias.setdefault(normalize(name), set()).add(p.id)
        self._alias = alias

    def resolve(self, ref: str | None) -> str | None:
        """Canonical place id, or None if the reference is missing, unknown or ambiguous."""
        if ref is None:
            return None
        if ref in self._by_id:
            return ref
        ids = self._alias.get(normalize(ref), set())
        return next(iter(ids)) if len(ids) == 1 else None

    def label(self, ref: str | None) -> str:
        return self.resolve(ref) or (ref if ref is not None else "?")

    def ancestors(self, place_id: str) -> list[str]:
        out: list[str] = []
        seen = {place_id}
        cur = self._by_id[place_id].parent_id
        while cur is not None and cur in self._by_id and cur not in seen:
            out.append(cur)
            seen.add(cur)
            cur = self._by_id[cur].parent_id
        return out

    def rel(self, ref_a: str | None, ref_b: str | None) -> PlaceRel:
        a, b = self.resolve(ref_a), self.resolve(ref_b)
        if a is None or b is None:
            return PlaceRel.UNKNOWN
        if a == b:
            return PlaceRel.SAME
        if b in self.ancestors(a) or a in self.ancestors(b):
            return PlaceRel.CONTAINS
        return PlaceRel.DISTINCT

    def within(self, place_id: str, ref: str | None) -> bool:
        """True if `ref` resolves to place_id or to a descendant of it."""
        r = self.resolve(ref)
        return r is not None and (r == place_id or place_id in self.ancestors(r))
