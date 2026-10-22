"""GraphStore: SQLite graph with provenance, anchors, entity resolution and queries.

Authoritative form of the graph (docs/data-schema.md 3.4, ADR-0002/0004). Standard library only.
Ingest is idempotent per chunk (input hash) and deterministic for a fixed ingest order; ingest
chunks in `chunk_id` order (`ingest_many` sorts them).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from detective_board.extract.schema import SCHEMA_VERSION, Extraction
from detective_board.graph.anchors import ChunkRef, resolve_quote
from detective_board.graph.normalize import is_unnamed_person, normalize_name, slugify
from detective_board.graph.results import EdgeHit, GraphResult, NodeHit, PathResult
from detective_board.graph.schema import GRAPH_BUILD_VERSION, migrate
from detective_board.graph.timenorm import TIME_NORM_VERSION, derive_time_norm
from detective_board.symbolic.model import Anchor

ENTITY_KINDS = ("person", "place", "item")
_PREFIX = {"person": "p", "place": "pl", "item": "i"}
_ALL_KINDS = ("person", "place", "item")


class DroppedItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    item_kind: str
    idx: int
    reason: str
    quote: str | None = None


class IngestReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    chunk_id: str
    status: Literal["inserted", "replaced", "unchanged"]
    entities: int = 0
    events: int = 0
    claims: int = 0
    edges: int = 0
    ambiguous_anchors: int = 0
    dropped: list[DroppedItem] = []
    warnings: list[str] = []


@dataclass
class _A:
    """A resolved anchor inside one chunk."""

    rel_start: int
    rel_end: int
    char_start: int | None
    char_end: int | None
    quote: str
    ambiguous: bool
    weak: bool  # ambiguous or only relative offsets valid -> low confidence (spec 2.1)


class _Ctx:
    def __init__(self, chunk: ChunkRef) -> None:
        self.chunk = chunk
        self.dropped: list[DroppedItem] = []
        self.warnings: list[str] = []
        self.touched: set[str] = set()
        self.n_entities = self.n_events = self.n_claims = self.n_edges = self.n_amb = 0

    def anchor(self, quote: str) -> _A | None:
        r = resolve_quote(self.chunk.text, quote)
        if not r.found or r.rel_start is None or r.rel_end is None:
            return None
        c = self.chunk
        cs = c.char_start + r.rel_start if c.contiguous else None
        ce = c.char_start + r.rel_end if c.contiguous else None
        self.n_amb += r.ambiguous
        return _A(
            r.rel_start, r.rel_end, cs, ce, r.quote, r.ambiguous, r.ambiguous or not c.contiguous
        )


def _j(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _anchor_from(story: str, chunk_id: str, r: sqlite3.Row) -> Anchor:
    rel = r["char_start"] is None  # only chunk-relative offsets are valid: weak by spec 2.1
    return Anchor(
        story=story,
        chunk_id=chunk_id,
        char_start=r["rel_start"] if rel else r["char_start"],
        char_end=r["rel_end"] if rel else r["char_end"],
        quote=r["quote"],
        rel_start=r["rel_start"],
        rel_end=r["rel_end"],
        ambiguous=bool(r["ambiguous"]) or rel,
    )


class GraphStore:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.isolation_level = None  # explicit transactions
        self.conn.execute("PRAGMA foreign_keys = ON")
        migrate(self.conn)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ------------------------------------------------------------------ ingest

    def ingest_many(
        self, items: Iterable[tuple[ChunkRef, Extraction]], *, force: bool = False
    ) -> list[IngestReport]:
        ordered = sorted(items, key=lambda it: (it[0].story, it[0].chunk_id))
        return [self.ingest(c, ex, force=force) for c, ex in ordered]

    def input_hash(self, chunk: ChunkRef, ex: Extraction) -> str:
        return _sha(
            _j(
                {
                    "chunk": [chunk.chunk_id, chunk.story, chunk.char_start, chunk.char_end],
                    "text": _sha(chunk.text),
                    "contiguous": chunk.contiguous,
                    "extraction": ex.model_dump(mode="json"),
                    "versions": [SCHEMA_VERSION, GRAPH_BUILD_VERSION, TIME_NORM_VERSION],
                }
            )
        )

    def ingest(self, chunk: ChunkRef, ex: Extraction, *, force: bool = False) -> IngestReport:
        """Upsert one chunk's extraction. Same chunk text + same extraction = no-op."""
        h = self.input_hash(chunk, ex)
        row = self.conn.execute(
            "SELECT input_hash FROM g_chunk WHERE chunk_id=?", (chunk.chunk_id,)
        ).fetchone()
        if row and row["input_hash"] == h and not force:
            return IngestReport(chunk_id=chunk.chunk_id, status="unchanged")
        ctx = _Ctx(chunk)
        with self._tx():
            if row:
                self._purge_chunk(chunk.chunk_id)
            self.conn.execute(
                "INSERT OR REPLACE INTO g_chunk(chunk_id, story, char_start, char_end, contiguous,"
                " text_sha, input_hash) VALUES (?,?,?,?,?,?,?)",
                (
                    chunk.chunk_id,
                    chunk.story,
                    chunk.char_start,
                    chunk.char_end,
                    int(chunk.contiguous),
                    _sha(chunk.text),
                    h,
                ),
            )
            self._ingest_entities(ctx, ex)
            claim_spans = self._ingest_claims(ctx, ex)
            self._ingest_events(ctx, ex, claim_spans)
            self._ingest_relations(ctx, ex)
            for nid in sorted(ctx.touched):
                self._refresh_entity(nid)
            for d in ctx.dropped:
                self.conn.execute(
                    "INSERT OR IGNORE INTO g_dropped(chunk_id,item_kind,idx,reason,quote)"
                    " VALUES (?,?,?,?,?)",
                    (chunk.chunk_id, d.item_kind, d.idx, d.reason, d.quote),
                )
        return IngestReport(
            chunk_id=chunk.chunk_id,
            status="replaced" if row else "inserted",
            entities=ctx.n_entities,
            events=ctx.n_events,
            claims=ctx.n_claims,
            edges=ctx.n_edges,
            ambiguous_anchors=ctx.n_amb,
            dropped=ctx.dropped,
            warnings=ctx.warnings,
        )

    def _purge_chunk(self, chunk_id: str) -> None:
        c = self.conn
        affected = [
            r[0]
            for r in c.execute(
                "SELECT DISTINCT node_id FROM g_mention WHERE chunk_id=? ORDER BY node_id",
                (chunk_id,),
            )
        ]
        c.execute("DELETE FROM g_edge WHERE chunk_id=?", (chunk_id,))
        c.execute("DELETE FROM g_node WHERE chunk_id=?", (chunk_id,))
        c.execute("DELETE FROM g_mention WHERE chunk_id=?", (chunk_id,))
        c.execute("DELETE FROM g_dropped WHERE chunk_id=?", (chunk_id,))
        for nid in affected:
            left = c.execute("SELECT 1 FROM g_mention WHERE node_id=? LIMIT 1", (nid,)).fetchone()
            used = c.execute(
                "SELECT 1 FROM g_edge WHERE src=? OR dst=? LIMIT 1", (nid, nid)
            ).fetchone()
            if left:
                self._refresh_entity(nid)
            elif not used:
                c.execute("DELETE FROM g_node WHERE id=?", (nid,))

    # -- entities

    def _lookup(self, story: str, kind: str, name: str) -> tuple[str | None, list[str]]:
        """Resolve by exact normalised name, then alias. Returns (id, ambiguous candidates)."""
        key = normalize_name(name, kind)
        if not key:
            return None, []
        unnamed = kind == "person" and is_unnamed_person(name)
        roles = ("name",) if unnamed else ("name", "alias")
        for role in roles:
            ids = self._match(story, kind, role, [key], unnamed)
            if len(ids) == 1:
                return ids[0], []
            if len(ids) > 1:
                return None, ids
        return None, []

    def _match(
        self, story: str, kind: str, role: str, keys: Sequence[str], unnamed: bool
    ) -> list[str]:
        if not keys:
            return []
        ph = ",".join("?" * len(keys))
        rows = self.conn.execute(
            "SELECT DISTINCT n.id FROM g_mention m JOIN g_node n ON n.id=m.node_id"
            f" WHERE n.story=? AND n.kind=? AND n.unnamed=? AND m.role=?"
            f" AND m.surface_norm IN ({ph})"
            " ORDER BY n.id",
            (story, kind, int(unnamed), role, *keys),
        )
        return [r[0] for r in rows]

    def _resolve_entity(
        self, story: str, kind: str, name: str, aliases: Sequence[str]
    ) -> tuple[str | None, list[str]]:
        """Entity item resolution. Tiers: same primary name; mention alias = known primary name;
        mention name = known alias. Alias-only overlap never merges (two 'Holmes' stay apart)."""
        key = normalize_name(name, kind)
        unnamed = kind == "person" and is_unnamed_person(name)
        ids = self._match(story, kind, "name", [key], unnamed)
        if len(ids) == 1:
            return ids[0], []
        if ids or unnamed:
            return None, ids
        akeys = sorted(
            {
                k
                for a in aliases
                if (k := normalize_name(a, kind)) and k != key and not is_unnamed_person(a)
            }
        )
        ids = self._match(story, kind, "name", akeys, False)
        if len(ids) == 1:
            return ids[0], []
        if ids:
            return None, ids
        ids = self._match(story, kind, "alias", [key], False)
        if len(ids) == 1:
            return ids[0], []
        return None, ids

    def _new_entity(self, story: str, kind: str, name: str, props: dict[str, Any]) -> str:
        key = normalize_name(name, kind)
        unnamed = kind == "person" and is_unnamed_person(name)
        base = f"{_PREFIX[kind]}:{story}:{slugify(key)}"
        nid, n = base, 1
        while self.conn.execute("SELECT 1 FROM g_node WHERE id=?", (nid,)).fetchone():
            n += 1
            nid = f"{base}-{n}"
        self.conn.execute(
            "INSERT INTO g_node(id,kind,story,name,norm_name,unnamed,props_json)"
            " VALUES (?,?,?,?,?,?,?)",
            (nid, kind, story, name.strip(), key, int(unnamed), _j(props)),
        )
        return nid

    def _add_mention(
        self, ctx: _Ctx, nid: str, surface: str, kind: str, role: str, a: _A, implicit: bool
    ) -> None:
        self.conn.execute(
            "INSERT INTO g_mention(node_id,chunk_id,surface,surface_norm,role,implicit,char_start,"
            "char_end,rel_start,rel_end,quote,ambiguous) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                nid,
                ctx.chunk.chunk_id,
                surface.strip(),
                normalize_name(surface, kind),
                role,
                int(implicit),
                a.char_start,
                a.char_end,
                a.rel_start,
                a.rel_end,
                a.quote,
                int(a.weak),
            ),
        )
        ctx.touched.add(nid)

    def _ingest_entities(self, ctx: _Ctx, ex: Extraction) -> None:
        story = ctx.chunk.story
        for i, e in enumerate(ex.entities):
            a = ctx.anchor(e.quote)
            if a is None:
                ctx.dropped.append(
                    DroppedItem(item_kind="entity", idx=i, reason="quote_not_found", quote=e.quote)
                )
                continue
            if not normalize_name(e.name, e.type):
                ctx.dropped.append(
                    DroppedItem(item_kind="entity", idx=i, reason="empty_name", quote=e.quote)
                )
                continue
            nid, cands = self._resolve_entity(story, e.type, e.name, e.aliases)
            if nid is None:
                props: dict[str, Any] = {}
                if cands:
                    props["ambiguous_resolution"] = cands
                    ctx.warnings.append(f"entity {e.name!r} ambiguous between {cands}; kept apart")
                nid = self._new_entity(story, e.type, e.name, props)
            ctx.n_entities += 1
            unnamed = e.type == "person" and is_unnamed_person(e.name)
            self._add_mention(ctx, nid, e.name, e.type, "name", a, False)
            seen = {normalize_name(e.name, e.type)}
            for al in e.aliases:
                k = normalize_name(al, e.type)
                if not k or k in seen:
                    continue
                seen.add(k)
                descr = unnamed or (e.type == "person" and is_unnamed_person(al))
                self._add_mention(ctx, nid, al, e.type, "descr" if descr else "alias", a, False)

    def _ref(
        self,
        ctx: _Ctx,
        name: str,
        kinds: tuple[str, ...],
        a: _A,
        *,
        create: bool,
    ) -> tuple[str | None, bool]:
        """Resolve an entity reference from an event/claim/relation. (node id, weak?)
        Unknown names are created as implicit low-confidence entities when `create`."""
        story = ctx.chunk.story
        for kind in kinds:
            nid, cands = self._lookup(story, kind, name)
            if nid:
                return nid, False
            if cands:
                ctx.warnings.append(f"reference {name!r} ambiguous between {cands}")
                return None, True
        if not create or not normalize_name(name, kinds[0]):
            return None, True
        nid = self._new_entity(story, kinds[0], name, {})
        self._add_mention(ctx, nid, name, kinds[0], "name", a, True)
        ctx.warnings.append(f"implicit {kinds[0]} {name!r} created from a reference")
        return nid, True

    # -- events, claims, relations

    def _edge(
        self,
        ctx: _Ctx,
        src: str,
        dst: str,
        rel: str,
        a: _A,
        *,
        weak: bool,
        props: dict[str, Any] | None = None,
    ) -> None:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO g_edge(src,dst,rel,props_json,confidence,chunk_id,char_start,"
            "char_end,rel_start,rel_end,quote,ambiguous) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                src,
                dst,
                rel,
                _j(props) if props else None,
                "low" if (weak or a.weak) else "high",
                ctx.chunk.chunk_id,
                a.char_start,
                a.char_end,
                a.rel_start,
                a.rel_end,
                a.quote,
                int(a.ambiguous),
            ),
        )
        ctx.n_edges += cur.rowcount

    def _insert_node(
        self, ctx: _Ctx, nid: str, kind: str, props: dict[str, Any], a: _A, weak: bool, why: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO g_node(id,kind,story,props_json,confidence,conf_reason,chunk_id,"
            "char_start,"
            "char_end,rel_start,rel_end,quote,ambiguous) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                nid,
                kind,
                ctx.chunk.story,
                _j(props),
                "low" if weak else "high",
                why or None,
                ctx.chunk.chunk_id,
                a.char_start,
                a.char_end,
                a.rel_start,
                a.rel_end,
                a.quote,
                int(a.ambiguous),
            ),
        )

    def _ingest_claims(self, ctx: _Ctx, ex: Extraction) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        cid = ctx.chunk.chunk_id
        for i, c in enumerate(ex.claims):
            a = ctx.anchor(c.quote)
            if a is None:
                ctx.dropped.append(
                    DroppedItem(item_kind="claim", idx=i, reason="quote_not_found", quote=c.quote)
                )
                continue
            spans.append((a.rel_start, a.rel_end))
            speaker, sweak = self._ref(ctx, c.speaker, ("person",), a, create=True)
            about, aweak = (None, False)
            if c.about:
                about, aweak = self._ref(ctx, c.about, _ALL_KINDS, a, create=False)
                if about is None:
                    ctx.warnings.append(f"claim {i}: about {c.about!r} not resolved")
            if speaker is None:
                ctx.dropped.append(
                    DroppedItem(
                        item_kind="claim", idx=i, reason="speaker_unresolved", quote=c.quote
                    )
                )
                continue
            weak = a.weak or sweak or aweak
            why = "ambiguous_anchor" if a.weak else ("weak_reference" if weak else "")
            nid = f"c:{cid}:{i}"
            props = {"content": c.content, "speaker": c.speaker, "about": c.about}
            self._insert_node(ctx, nid, "claim", props, a, weak, why)
            ctx.n_claims += 1
            self._edge(ctx, speaker, nid, "ASSERTS", a, weak=sweak)
            if about:
                self._edge(ctx, nid, about, "ABOUT", a, weak=aweak)
        return spans

    def _ingest_events(self, ctx: _Ctx, ex: Extraction, claim_spans: list[tuple[int, int]]) -> None:
        cid = ctx.chunk.chunk_id
        for i, e in enumerate(ex.events):
            a = ctx.anchor(e.quote)
            if a is None:
                ctx.dropped.append(
                    DroppedItem(item_kind="event", idx=i, reason="quote_not_found", quote=e.quote)
                )
                continue
            weak = a.weak
            people: list[str] = []
            for name in e.participants:
                pid, w = self._ref(ctx, name, ("person",), a, create=True)
                weak |= w
                if pid and pid not in people:
                    people.append(pid)
            place: str | None = None
            if e.place:
                place, w = self._ref(ctx, e.place, ("place",), a, create=True)
                weak |= w
            tn = derive_time_norm(e.time_text) if e.time_text else None
            reported = any(s <= a.rel_start and a.rel_end <= t for s, t in claim_spans)
            props = {
                "description": e.description,
                "time_text": e.time_text,
                "time_norm": tn.model_dump(mode="json") if tn else None,
                "narrator": not reported,
            }
            why = "ambiguous_anchor" if a.weak else ("weak_reference" if weak else "")
            nid = f"e:{cid}:{i}"
            self._insert_node(ctx, nid, "event", props, a, weak, why)
            ctx.n_events += 1
            for pid in people:
                self._edge(ctx, pid, nid, "PARTICIPATED_IN", a, weak=False)
            if place:
                self._edge(ctx, nid, place, "OCCURRED_AT", a, weak=False)

    def _ingest_relations(self, ctx: _Ctx, ex: Extraction) -> None:
        for i, r in enumerate(ex.relations):
            a = ctx.anchor(r.quote)
            if a is None:
                ctx.dropped.append(
                    DroppedItem(
                        item_kind="relation", idx=i, reason="quote_not_found", quote=r.quote
                    )
                )
                continue
            s, _ = self._ref(ctx, r.subject, _ALL_KINDS, a, create=False)
            o, _ = self._ref(ctx, r.object, _ALL_KINDS, a, create=False)
            if s is None or o is None:
                ctx.dropped.append(
                    DroppedItem(
                        item_kind="relation", idx=i, reason="entity_unresolved", quote=r.quote
                    )
                )
                continue
            self._edge(
                ctx,
                s,
                o,
                "RELATION",
                a,
                weak=False,
                props={"predicate": r.predicate.strip().lower()},
            )

    def _refresh_entity(self, nid: str) -> None:
        """Recompute display name, aliases and confidence of an entity from its mentions."""
        c = self.conn
        node = c.execute(
            "SELECT kind, unnamed, props_json FROM g_node WHERE id=?", (nid,)
        ).fetchone()
        if node is None:
            return
        rows = c.execute(
            "SELECT surface, surface_norm, role, implicit, ambiguous FROM g_mention"
            " WHERE node_id=? ORDER BY id",
            (nid,),
        ).fetchall()
        if not rows:
            return
        names = [r for r in rows if r["role"] == "name"] or rows
        best = min(
            names, key=lambda r: (-len(r["surface_norm"].split()), len(r["surface"]), r["surface"])
        )
        by_norm: dict[str, str] = {}
        for r in rows:
            if r["surface_norm"] != best["surface_norm"]:
                cur = by_norm.get(r["surface_norm"])
                by_norm[r["surface_norm"]] = min(cur, r["surface"]) if cur else r["surface"]
        props = json.loads(node["props_json"])
        props["aliases"] = sorted(by_norm.values())
        props["implicit_only"] = all(r["implicit"] for r in rows)
        reason = ""
        if node["unnamed"]:
            reason = "unnamed"
        elif props.get("ambiguous_resolution"):
            reason = "ambiguous_resolution"
        elif props["implicit_only"]:
            reason = "implicit_only"
        elif all(r["ambiguous"] for r in rows):
            reason = "ambiguous_anchor"
        c.execute(
            "UPDATE g_node SET name=?, norm_name=?, props_json=?, confidence=?, conf_reason=?"
            " WHERE id=?",
            (
                best["surface"],
                best["surface_norm"],
                _j(props),
                "low" if reason else "high",
                reason or None,
                nid,
            ),
        )

    # ------------------------------------------------------------------ overlays

    def set_overlay(
        self, node_id: str, key: str, value: Any, *, confidence: str = "low", source: str = "manual"
    ) -> None:
        """Attach a derived/curated value (survives re-ingest). Keys used by the FactSource:
        `story_day` (int, events) and `prop` (PresenceProp/OrderProp dict, claims)."""
        if not self.conn.execute("SELECT 1 FROM g_node WHERE id=?", (node_id,)).fetchone():
            raise KeyError(node_id)
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        with self._tx():
            self.conn.execute(
                "INSERT OR REPLACE INTO g_overlay(node_id,key,value_json,confidence,source)"
                " VALUES (?,?,?,?,?)",
                (node_id, key, _j(value), confidence, source),
            )

    def set_event_day(self, event_id: str, day: int, *, confidence: str = "low") -> None:
        self.set_overlay(event_id, "story_day", day, confidence=confidence)

    def set_claim_prop(self, claim_id: str, prop: Any, *, confidence: str = "low") -> None:
        self.set_overlay(claim_id, "prop", prop, confidence=confidence, source="normaliser")

    # ------------------------------------------------------------------ queries

    def stats(self) -> dict[str, int]:
        q = self.conn.execute
        out = {r["kind"]: r["n"] for r in q("SELECT kind, COUNT(*) n FROM g_node GROUP BY kind")}
        out["edges"] = q("SELECT COUNT(*) FROM g_edge").fetchone()[0]
        out["chunks"] = q("SELECT COUNT(*) FROM g_chunk").fetchone()[0]
        return dict(sorted(out.items()))

    def _node_hit(self, r: sqlite3.Row, hops: int | None = None, max_anchors: int = 5) -> NodeHit:
        props = json.loads(r["props_json"])
        if r["kind"] in ENTITY_KINDS:
            arows = self.conn.execute(
                "SELECT chunk_id, char_start, char_end, rel_start, rel_end, quote, ambiguous"
                " FROM g_mention WHERE node_id=? GROUP BY chunk_id, rel_start, rel_end"
                " ORDER BY chunk_id, rel_start, rel_end",
                (r["id"],),
            ).fetchall()
            anchors = [_anchor_from(r["story"], a["chunk_id"], a) for a in arows[:max_anchors]]
            total = len(arows)
        else:
            anchors = [_anchor_from(r["story"], r["chunk_id"], r)] if r["chunk_id"] else []
            total = len(anchors)
        return NodeHit(
            id=r["id"],
            kind=r["kind"],
            story=r["story"],
            name=r["name"],
            aliases=props.get("aliases", []),
            confidence=r["confidence"],
            provenance=r["provenance"],
            props={k: v for k, v in props.items() if k != "aliases"},
            anchors=anchors,
            anchor_total=total,
            hops=hops,
        )

    def _edge_hit(self, r: sqlite3.Row) -> EdgeHit:
        story = self.conn.execute(
            "SELECT story FROM g_chunk WHERE chunk_id=?", (r["chunk_id"],)
        ).fetchone()["story"]
        return EdgeHit(
            id=r["id"],
            rel=r["rel"],
            src=r["src"],
            dst=r["dst"],
            confidence=r["confidence"],
            provenance=r["provenance"],
            props=json.loads(r["props_json"]) if r["props_json"] else {},
            anchor=_anchor_from(story, r["chunk_id"], r),
        )

    def _nodes(self, ids: Iterable[str], hops: dict[str, int] | None = None) -> list[NodeHit]:
        out = []
        for nid in ids:
            r = self.conn.execute("SELECT * FROM g_node WHERE id=?", (nid,)).fetchone()
            if r:
                out.append(self._node_hit(r, None if hops is None else hops.get(nid)))
        return out

    def get_node(self, node_id: str) -> NodeHit | None:
        r = self.conn.execute("SELECT * FROM g_node WHERE id=?", (node_id,)).fetchone()
        return self._node_hit(r) if r else None

    def resolve(
        self, ref: str, *, story: str | None = None, kinds: Sequence[str] = ENTITY_KINDS
    ) -> list[str]:
        """Node ids for a node id or an entity name/alias (normalised); sorted by id.
        Name matches ordered: primary-name matches first, then alias matches."""
        r = self.conn.execute("SELECT id, story, kind FROM g_node WHERE id=?", (ref,)).fetchone()
        if r:
            return [r["id"]] if (story is None or r["story"] == story) else []
        found: dict[str, tuple[int, str, str]] = {}
        for kind in kinds:
            key = normalize_name(ref, kind)
            if not key:
                continue
            sql = (
                "SELECT n.id, n.story, MIN(CASE m.role WHEN 'name' THEN 0 ELSE 1 END) rk"
                " FROM g_mention m JOIN g_node n ON n.id=m.node_id"
                " WHERE n.kind=? AND m.surface_norm=?"
            )
            args: list[Any] = [kind, key]
            if story is not None:
                sql += " AND n.story=?"
                args.append(story)
            for x in self.conn.execute(sql + " GROUP BY n.id", args):
                found[x["id"]] = (x["rk"], x["story"], x["id"])
        return [k for k, _ in sorted(found.items(), key=lambda kv: kv[1])]

    def find_entities(
        self,
        name: str,
        *,
        kind: str | None = None,
        story: str | None = None,
        limit: int = 50,
    ) -> GraphResult:
        ids = self.resolve(name, story=story, kinds=(kind,) if kind else ENTITY_KINDS)
        trunc = len(ids) > limit
        return GraphResult(
            query_kind="find_entities",
            seeds=ids[:limit],
            nodes=self._nodes(ids[:limit]),
            truncated=trunc,
        )

    def _incident(self, nid: str, direction: str, rels: Sequence[str] | None) -> list[sqlite3.Row]:
        cond = {"out": "src=?", "in": "dst=?", "both": "(src=? OR dst=?)"}[direction]
        args: list[Any] = [nid] * (2 if direction == "both" else 1)
        sql = f"SELECT * FROM g_edge WHERE {cond}"
        if rels:
            sql += f" AND rel IN ({','.join('?' * len(rels))})"
            args += list(rels)
        return self.conn.execute(sql + " ORDER BY id", args).fetchall()

    def neighbours(
        self,
        ref: str,
        k: int = 1,
        *,
        story: str | None = None,
        rels: Sequence[str] | None = None,
        direction: Literal["out", "in", "both"] = "both",
        max_nodes: int = 200,
    ) -> GraphResult:
        """k-hop BFS around `ref` (node id or entity name). Deterministic: frontier and edges are
        visited in id order. `nodes` ordered by (hops, id); `edges` (by id) are those traversed."""
        seeds = self.resolve(ref, story=story)
        dist = {s: 0 for s in seeds}
        edges: dict[int, sqlite3.Row] = {}
        truncated = False
        frontier = sorted(seeds)
        for depth in range(k):
            nxt: set[str] = set()
            for nid in frontier:
                for e in self._incident(nid, direction, rels):
                    other = e["dst"] if e["src"] == nid else e["src"]
                    if other not in dist:
                        if len(dist) >= max_nodes:
                            truncated = True
                            continue
                        dist[other] = depth + 1
                        nxt.add(other)
                    edges[e["id"]] = e
            frontier = sorted(nxt)
        order = sorted(dist, key=lambda n: (dist[n], n))
        return GraphResult(
            query_kind="neighbours",
            seeds=sorted(seeds),
            nodes=self._nodes(order, dist),
            edges=[self._edge_hit(edges[i]) for i in sorted(edges)],
            truncated=truncated,
        )

    def _bundle(
        self,
        kind: str,
        seeds: list[str],
        event_ids: list[str],
        rels: Sequence[str],
        extra_ids: Iterable[str] = (),
    ) -> GraphResult:
        """Events in text order plus their edges of `rels` and the nodes those edges touch."""
        ph = ",".join("?" * len(event_ids))
        edges = (
            self.conn.execute(
                f"SELECT * FROM g_edge WHERE rel IN ({','.join('?' * len(rels))})"
                f" AND (src IN ({ph}) OR dst IN ({ph})) ORDER BY id",
                [*rels, *event_ids, *event_ids],
            ).fetchall()
            if event_ids
            else []
        )
        others = sorted(
            {n for e in edges for n in (e["src"], e["dst"])} | set(extra_ids) | set(seeds)
        )
        ordered = [
            *seeds,
            *event_ids,
            *[n for n in others if n not in seeds and n not in event_ids],
        ]
        return GraphResult(
            query_kind=kind,
            seeds=seeds,
            nodes=self._nodes(dict.fromkeys(ordered)),
            edges=[self._edge_hit(e) for e in edges],
        )

    def _events_of(self, ids: list[str], rel: str, side: str) -> list[str]:
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        other = "dst" if side == "src" else "src"
        rows = self.conn.execute(
            f"SELECT DISTINCT n.id FROM g_edge e JOIN g_node n ON n.id=e.{other}"
            f" WHERE e.rel=? AND e.{side} IN ({ph}) AND n.kind='event'"
            " ORDER BY n.story, n.chunk_id, n.rel_start, n.id",
            [rel, *ids],
        )
        return [r[0] for r in rows]

    def events_by_person(self, person: str, *, story: str | None = None) -> GraphResult:
        ids = self.resolve(person, story=story, kinds=("person",))
        ev = self._events_of(ids, "PARTICIPATED_IN", "src")
        return self._bundle("events_by_person", ids, ev, ("PARTICIPATED_IN", "OCCURRED_AT"))

    def events_by_place(self, place: str, *, story: str | None = None) -> GraphResult:
        ids = self.resolve(place, story=story, kinds=("place",))
        ev = self._events_of(ids, "OCCURRED_AT", "dst")
        return self._bundle("events_by_place", ids, ev, ("PARTICIPATED_IN", "OCCURRED_AT"))

    def claims_by_speaker(self, person: str, *, story: str | None = None) -> GraphResult:
        ids = self.resolve(person, story=story, kinds=("person",))
        cl = self._events_of_claims(ids)
        return self._bundle("claims_by_speaker", ids, cl, ("ASSERTS", "ABOUT"))

    def _events_of_claims(self, ids: list[str]) -> list[str]:
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        rows = self.conn.execute(
            "SELECT DISTINCT n.id FROM g_edge e JOIN g_node n ON n.id=e.dst"
            f" WHERE e.rel='ASSERTS' AND e.src IN ({ph}) AND n.kind='claim'"
            " ORDER BY n.story, n.chunk_id, n.rel_start, n.id",
            ids,
        )
        return [r[0] for r in rows]

    def shortest_path(
        self,
        a: str,
        b: str,
        *,
        story: str | None = None,
        max_hops: int = 6,
        rels: Sequence[str] | None = None,
    ) -> PathResult:
        """Shortest undirected path (fewest edges) between two entities/nodes. Ties are broken by
        smallest node id per layer and smallest edge id per node, so the result is stable.
        `nodes`/`edges` are in path order."""
        src, dst = self.resolve(a, story=story), set(self.resolve(b, story=story))
        seeds = [*sorted(src), *sorted(dst - set(src))]
        if not src or not dst:
            return PathResult(query_kind="shortest_path", seeds=seeds, found=False)
        parent: dict[str, tuple[str, sqlite3.Row] | None] = {s: None for s in sorted(src)}
        hit = sorted(set(src) & dst)
        layer = sorted(src)
        depth = 0
        while not hit and layer and depth < max_hops:
            depth += 1
            nxt: list[str] = []
            for nid in layer:
                for e in self._incident(nid, "both", rels):
                    other = e["dst"] if e["src"] == nid else e["src"]
                    if other not in parent:
                        parent[other] = (nid, e)
                        nxt.append(other)
            layer = sorted(nxt)
            hit = sorted(n for n in layer if n in dst)
        if not hit:
            return PathResult(query_kind="shortest_path", seeds=seeds, found=False)
        path_nodes = [hit[0]]
        path_edges: list[sqlite3.Row] = []
        while (p := parent[path_nodes[-1]]) is not None:
            path_nodes.append(p[0])
            path_edges.append(p[1])
        path_nodes.reverse()
        path_edges.reverse()
        return PathResult(
            query_kind="shortest_path",
            seeds=seeds,
            nodes=self._nodes(path_nodes, {n: i for i, n in enumerate(path_nodes)}),
            edges=[self._edge_hit(e) for e in path_edges],
            found=True,
            hops=len(path_edges),
        )
