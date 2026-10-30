"""Curated crime SCENES for the suspects / alibi-exclusion board (docs/symbolic-layer.md 11.6).

    python -m detective_board.extract.scenes [--file data/curated/scenes.jsonl] \\
        [--clean-dir data/clean] [--graph-db data/graph/graph.sqlite]

A scene is a place, a time window and a victim for one story, with ONE verbatim quote of the text
that states the crime time or place. It cannot be derived automatically (the extraction has no
"crime scene" concept), so the team writes it by hand (prepared with tooling support, human re-check
pending) and the loader refuses anything that is not grounded: the quote must be a verbatim span of
`data/clean/<story>.txt`, the time expression must be in the quote and give an exact clock time
that equals the window, the place and the victim must be in the quote or declared `inferred`
(with a note that says why), and the place must exist in the graph or be declared
(`place_declared`). Nothing here is evidence about guilt: the board built on a scene only reports
what the text says about where people were (testimony, not proof).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from detective_board.extract.curated import locate_quote, normalise_quote
from detective_board.extract.curated_schema import CURATED_REVIEW, check_review, curated_day
from detective_board.extract.normalise import normalise_time
from detective_board.graph.normalize import fold_text

SCENES_SCHEMA_VERSION = "scenes-1"
DEFAULT_FILE = "data/curated/scenes.jsonl"
SCENE_CURATED_BY = "team (prepared with tooling support, human re-check pending)"
SCENE_MARK = f"curated by team, prepared with tooling support, {CURATED_REVIEW}"
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

Slot = Literal["place", "victim"]


class Scene(BaseModel):
    """One human-checked crime scene. `day_key` is the curated story-day key shared with
    `data/curated/presence_demo.jsonl`: facts with the same key of the same story are one day, so
    the board can compare them with the window. `titles` are the names by which the story and the
    case are called in a question (the router matches them), besides the place and the victim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    story: str
    place: str = Field(description="Place name as the graph holds it (or declared)")
    place_declared: bool = Field(
        default=False, description="True when the place is not expected to be a graph place"
    )
    day_key: str
    time_text: str = Field(description="Time expression verbatim from the quote")
    start_min: int = Field(ge=0, le=1440)
    end_min: int = Field(ge=0, le=1440)
    victim: str
    victim_aliases: list[str] = Field(default_factory=list)
    titles: list[str] = Field(min_length=1)
    quote: str
    curated_by: str
    note: str
    inferred: list[Slot] = Field(default_factory=list)
    reviewed_by: str | None = None
    reviewed_on: str | None = None

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("id must be lowercase letters, digits, '-' or '_'")
        return v

    @field_validator("day_key")
    @classmethod
    def _key_ok(cls, v: str) -> str:
        if not _KEY.match(v):
            raise ValueError("day_key must be lowercase kebab-case")
        return v

    @field_validator("story")
    @classmethod
    def _story_ok(cls, v: str) -> str:
        if not _SLUG.match(v):
            raise ValueError("story must be a story slug")
        return v

    @field_validator("place", "victim", "time_text", "quote", "curated_by", "note")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("titles", "victim_aliases")
    @classmethod
    def _items_non_empty(cls, v: list[str]) -> list[str]:
        if any(not x.strip() for x in v):
            raise ValueError("entries must not be empty")
        return v

    @model_validator(mode="after")
    def _ordered(self) -> Scene:
        check_review(self.reviewed_by, self.reviewed_on)
        if self.start_min > self.end_min:
            raise ValueError("start_min must not exceed end_min")
        return self

    @property
    def story_day(self) -> int:
        return curated_day(self.story, self.day_key)

    def terms(self) -> list[str]:
        """Names by which a question points at this scene: place, titles, victim and aliases."""
        return list(dict.fromkeys([self.place, *self.titles, self.victim, *self.victim_aliases]))


def load_file(path: str | Path) -> list[Scene]:
    """Parse a JSONL file of scenes. Blank lines and `#` lines are skipped; duplicate ids and
    invalid records raise ValueError with the line number."""
    scenes: list[Scene] = []
    seen: set[str] = set()
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            scene = Scene.model_validate(json.loads(line))
        except ValueError as exc:
            raise ValueError(f"{path}:{n}: {exc}") from exc
        if scene.id in seen:
            raise ValueError(f"{path}:{n}: duplicate id {scene.id!r}")
        seen.add(scene.id)
        scenes.append(scene)
    return scenes


def _name_in(name: str, folded_quote: str) -> bool:
    return fold_text(name.split()[-1]) in folded_quote.split()


def problems(
    scene: Scene, clean_text: str, graph_places: Collection[str] | None = None
) -> list[str]:
    """Why a scene cannot be used as written; empty when it is sound. `graph_places` (names and
    aliases of the story's places in the graph) enables the "place exists or is declared" check."""
    sid = scene.id
    if locate_quote(clean_text, scene.quote) is None:
        return [f"{sid}: quote is not a verbatim span of the story text"]
    out: list[str] = []
    q = normalise_quote(scene.quote).casefold()
    if normalise_quote(scene.time_text).casefold() not in q:
        out.append(f"{sid}: time_text {scene.time_text!r} is not in the quote")
    spec = normalise_time(scene.time_text)
    if spec is None or not spec.exact or spec.lo is None or spec.hi is None:
        out.append(f"{sid}: time_text {scene.time_text!r} is not an exact clock time")
    elif (spec.lo, spec.hi) != (scene.start_min, scene.end_min):
        out.append(
            f"{sid}: window {scene.start_min}-{scene.end_min} differs from the time_text "
            f"({spec.lo}-{spec.hi} minutes)"
        )
    place_in = normalise_quote(scene.place).casefold() in q
    if not place_in and "place" not in scene.inferred:
        out.append(f"{sid}: place {scene.place!r} is not in the quote; declare it inferred")
    if place_in and "place" in scene.inferred:
        out.append(f"{sid}: place {scene.place!r} is in the quote but declared inferred")
    victim_in = _name_in(scene.victim, fold_text(scene.quote))
    if not victim_in and "victim" not in scene.inferred:
        out.append(f"{sid}: victim {scene.victim!r} is not in the quote; declare it inferred")
    if victim_in and "victim" in scene.inferred:
        out.append(f"{sid}: victim {scene.victim!r} is in the quote but declared inferred")
    if scene.inferred and not re.search(r"infer|resolv|context|imply|implied", scene.note, re.I):
        out.append(f"{sid}: inferred slots need a note that says why")
    if scene.curated_by != SCENE_CURATED_BY:
        out.append(f"{sid}: curated_by must be {SCENE_CURATED_BY!r}")
    if graph_places is not None and not scene.place_declared:
        known = {normalise_quote(p).casefold().removeprefix("the ") for p in graph_places}
        if normalise_quote(scene.place).casefold().removeprefix("the ") not in known:
            out.append(f"{sid}: place {scene.place!r} is not in the graph; set place_declared")
    return out


def validate(
    scenes: Iterable[Scene],
    clean_texts: dict[str, str],
    graph_places: Mapping[str, Collection[str]] | None = None,
) -> list[str]:
    """Every problem of every scene (empty list: all sound)."""
    out: list[str] = []
    for s in scenes:
        clean = clean_texts.get(s.story)
        if clean is None:
            out.append(f"{s.id}: no clean text for story {s.story!r}")
            continue
        out += problems(s, clean, None if graph_places is None else graph_places.get(s.story, ()))
    return out


# ---------------------------------------------------------------------------- matching
def _term_rx(term: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in normalise_quote(term).split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", re.I)


def match_scene(scenes: Sequence[Scene], question: str) -> Scene | None:
    """The scene a question points at: the scene with the most of its terms (place, titles, victim,
    aliases) in the question. Scenes of different stories tied on the best score are ambiguous:
    None, never a guess. No term, no scene."""
    q = normalise_quote(question)
    scored: list[tuple[int, int, Scene]] = []
    for i, s in enumerate(scenes):
        n = sum(1 for t in s.terms() if _term_rx(t).search(q))
        if n:
            scored.append((n, -i, s))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0][0]
    top = [s for n, _, s in scored if n == best]
    if len({s.story for s in top}) > 1:
        return None
    return top[0]


# ---------------------------------------------------------------------------- anchors
@dataclass(frozen=True)
class SceneAnchor:
    """Where the scene quote sits in the story: the chunk that holds it and absolute offsets."""

    story: str
    chunk_id: str
    char_start: int
    char_end: int
    quote: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "story": self.story,
            "chunk_id": self.chunk_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote": self.quote,
        }


def scene_anchor(scene: Scene, chunks: Iterable[Any]) -> SceneAnchor | None:
    """Anchor of the scene quote in the first chunk (by id) of its story that holds all of it, with
    the chunk's own characters. `chunks` are `graph.anchors.ChunkRef`. None: no chunk holds it."""
    for c in sorted((c for c in chunks if c.story == scene.story), key=lambda c: c.chunk_id):
        span = locate_quote(c.text, scene.quote)
        if span is not None:
            return SceneAnchor(
                scene.story,
                c.chunk_id,
                c.char_start + span[0],
                c.char_start + span[1],
                c.text[span[0] : span[1]],
            )
    return None


def load_anchors(
    scenes: Sequence[Scene], chunks_path: str | Path, clean_dir: str | Path
) -> dict[str, SceneAnchor]:
    """Anchors of all scenes by scene id (a scene with no holding chunk is left out)."""
    from detective_board.extract.curated import load_chunks

    chunks = load_chunks(chunks_path, {s.story for s in scenes}, clean_dir)
    out: dict[str, SceneAnchor] = {}
    for s in scenes:
        a = scene_anchor(s, chunks)
        if a is not None:
            out[s.id] = a
    return out


@dataclass(frozen=True)
class SceneIndex:
    """The scenes the agent knows, with the anchor of each scene quote. Empty by default: without
    scenes nothing is routed to the board."""

    scenes: tuple[Scene, ...] = ()
    anchors: Mapping[str, SceneAnchor] = field(default_factory=dict)

    def match(self, question: str) -> Scene | None:
        return match_scene(self.scenes, question)

    def anchor(self, scene: Scene) -> SceneAnchor | None:
        return self.anchors.get(scene.id)

    def __bool__(self) -> bool:
        return bool(self.scenes)


def load_index(path: str | Path) -> SceneIndex:
    """Scenes of `path` (a file in `<data>/curated/`), validated against `<data>/clean` and anchored
    in `<data>/chunks.jsonl`. Raises ValueError listing every problem: a scene that is not grounded
    must never be used."""
    p = Path(path)
    data = p.resolve().parent.parent
    scenes = load_file(p)
    clean = {
        s: (data / "clean" / f"{s}.txt").read_text(encoding="utf-8")
        for s in {sc.story for sc in scenes}
    }
    errors = validate(scenes, clean)
    anchors = load_anchors(scenes, data / "chunks.jsonl", data / "clean") if scenes else {}
    errors += [f"{s.id}: no chunk holds the whole quote" for s in scenes if s.id not in anchors]
    if errors:
        raise ValueError("scenes not usable:\n" + "\n".join(errors))
    return SceneIndex(tuple(scenes), anchors)


def graph_place_names(graph_db: str | Path) -> dict[str, set[str]]:
    """Place names and aliases per story from a graph file (opened read-only)."""
    import sqlite3

    con = sqlite3.connect(f"file:{graph_db}?mode=ro", uri=True)
    try:
        out: dict[str, set[str]] = {}
        for story, name, props in con.execute(
            "SELECT story, name, props_json FROM g_node WHERE kind='place'"
        ):
            names = out.setdefault(story, set())
            names.add(name)
            names.update(json.loads(props or "{}").get("aliases", []))
        return out
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scenes", description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--file", default=DEFAULT_FILE, help=f"scenes, JSONL ({DEFAULT_FILE})")
    ap.add_argument("--clean-dir", default="data/clean")
    ap.add_argument("--graph-db", help="graph file: also check that each place exists in it")
    ns = ap.parse_args(argv)
    scenes = load_file(ns.file)
    clean = {
        s: (Path(ns.clean_dir) / f"{s}.txt").read_text(encoding="utf-8")
        for s in {sc.story for sc in scenes}
    }
    places = graph_place_names(ns.graph_db) if ns.graph_db else None
    errors = validate(scenes, clean, places)
    if errors:
        print("scenes not valid:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print(f"scenes: {len(scenes)} valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
