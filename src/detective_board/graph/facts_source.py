"""SqliteFactSource: builds the symbolic layer's FactBase from the graph tables (ADR-0004)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter

from detective_board.graph.store import GraphStore, _anchor_from
from detective_board.symbolic.facts import ClaimRec, EventRec, FactBase, PlaceRec, Prop
from detective_board.symbolic.model import Anchor, TimeSpec

ALL_STORIES = "*"
# RELATION predicates read as "subject is inside object" (place containment for PlaceRec.parent_id)
PARENT_PREDICATES = frozenset({"in", "inside", "within", "part of", "located in", "situated in"})
_PROP = TypeAdapter(Prop)


class SqliteFactSource:
    """Implements `detective_board.symbolic.model.FactSource`.

    `load(story)` reads one story, `load(ALL_STORIES)` the whole corpus. `assume_day` is an opt-in
    for single-day cases: events whose day is unknown get that day, and their time becomes `low`
    confidence (the rules never assume a day by themselves). Per-event days set with
    `GraphStore.set_event_day` take precedence.
    """

    def __init__(self, store: GraphStore, *, assume_day: int | None = None) -> None:
        self.store = store
        self.assume_day = assume_day

    def _overlays(self, key: str) -> dict[str, tuple[Any, str]]:
        rows = self.store.conn.execute(
            "SELECT node_id, value_json, confidence FROM g_overlay WHERE key=?", (key,)
        )
        return {r["node_id"]: (json.loads(r["value_json"]), r["confidence"]) for r in rows}

    def _time(
        self,
        props: dict[str, Any],
        day_ov: tuple[Any, str] | None,
        time_ov: tuple[Any, str] | None = None,
    ) -> TimeSpec | None:
        text = props.get("time_text") or props.get("time_text_inherited")
        if not text:
            return None
        inherited = not props.get("time_text")  # copied context: LOW and never exact
        if time_ov is not None:  # the normaliser's TimeSpec (extract/normalise.py) wins
            t = TimeSpec.model_validate(time_ov[0])
            day, dconf = day_ov if day_ov else (t.day, t.confidence)
            if day is None and self.assume_day is not None:
                day, dconf = self.assume_day, "low"
            low = inherited or t.confidence == "low" or (day is not None and dconf == "low")
            upd: dict[str, Any] = {"day": day, "confidence": "low" if low else "high"}
            if inherited:
                upd["exact"] = False
            return t.model_copy(update=upd)
        tn = props.get("time_norm") or {}
        day, dconf = day_ov if day_ov else (self.assume_day, "low")
        low = (
            inherited
            or tn.get("confidence", "low") == "low"
            or (day is not None and dconf == "low")
        )
        return TimeSpec(
            day=day,
            lo=tn.get("lo"),
            hi=tn.get("hi"),
            exact=bool(tn.get("exact", False)) and not inherited,
            confidence="low" if low else "high",
            time_text=text,
        )

    def load(self, story: str) -> FactBase:
        conn = self.store.conn
        all_ = story == ALL_STORIES
        w, args = ("", []) if all_ else (" AND story=?", [story])

        def nodes(kind: str):
            return conn.execute(
                f"SELECT * FROM g_node WHERE kind=?{w} ORDER BY id", [kind, *args]
            ).fetchall()

        edges: dict[str, list] = {}
        for e in conn.execute(
            "SELECT * FROM g_edge WHERE rel IN"
            " ('PARTICIPATED_IN','OCCURRED_AT','ASSERTS','RELATION') ORDER BY id"
        ):
            edges.setdefault(e["rel"], []).append(e)

        place_ids = {r["id"] for r in nodes("place")}
        parent: dict[str, str] = {}
        for e in edges.get("RELATION", []):
            pred = json.loads(e["props_json"] or "{}").get("predicate")
            if e["src"] in place_ids and e["dst"] in place_ids and pred in PARENT_PREDICATES:
                parent.setdefault(e["src"], e["dst"])
        places = []
        for r in nodes("place"):
            p = json.loads(r["props_json"])
            places.append(
                PlaceRec(
                    id=r["id"],
                    name=r["name"],
                    aliases=p.get("aliases", []),
                    parent_id=parent.get(r["id"]),
                )
            )

        people: dict[str, list[str]] = {}
        for e in edges.get("PARTICIPATED_IN", []):
            people.setdefault(e["dst"], []).append(e["src"])
        where: dict[str, str] = {}
        for e in edges.get("OCCURRED_AT", []):
            where.setdefault(e["src"], e["dst"])
        days = self._overlays("story_day")
        times = self._overlays("time")
        events = []
        for r in nodes("event"):
            p = json.loads(r["props_json"])
            events.append(
                EventRec(
                    id=r["id"],
                    description=p.get("description", ""),
                    time=self._time(p, days.get(r["id"]), times.get(r["id"])),
                    place_ref=where.get(r["id"]),
                    participants=people.get(r["id"], []),
                    anchors=[self._anchor(r)],
                    confidence=r["confidence"],
                    narrator=bool(p.get("narrator", True)),
                    occurrence_id=p.get("occurrence"),
                    curated=bool(p.get("curated", False)),
                )
            )

        speaker = {e["dst"]: e["src"] for e in reversed(edges.get("ASSERTS", []))}
        props_ov = self._overlays("prop")
        claims = []
        for r in nodes("claim"):
            if r["id"] not in speaker:
                continue
            p = json.loads(r["props_json"])
            prop, pconf = None, "high"
            if r["id"] in props_ov:
                raw, pconf = props_ov[r["id"]]
                prop = _PROP.validate_python(raw)
            claims.append(
                ClaimRec(
                    id=r["id"],
                    speaker_id=speaker[r["id"]],
                    content=p.get("content", ""),
                    prop=prop,
                    anchors=[self._anchor(r)],
                    confidence="low" if "low" in (r["confidence"], pconf) else "high",
                    curated=bool(p.get("curated", False)),
                )
            )
        return FactBase(story=story, places=places, events=events, claims=claims)

    def _anchor(self, r) -> Anchor:
        return _anchor_from(r["story"], r["chunk_id"], r)
