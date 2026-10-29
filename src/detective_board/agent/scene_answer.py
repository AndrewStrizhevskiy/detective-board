"""Suspects / alibi-exclusion board for a crime scene: a deterministic answer over `scene_board`.

For the scene the question points at (`data/curated/scenes.jsonl`, `extract/scenes.py`), one line
per person of the story that the graph knows: excluded by testimony (the text places them elsewhere
at the scene's time, rule R1 `check_alibi` contradicted), placed at the scene (supported), or not
excluded (the graph has no usable placed event at that time). Every decisive line carries the
verbatim `[n: "quote"]`, the provenance label (derived / conditional) and `curated` where a fact is
human-checked. No model call, no ranking, no verdict about guilt: the closing block says so.
docs/symbolic-layer.md 11.6.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from detective_board.extract.scenes import SCENE_MARK, Scene, SceneIndex, load_index

from .events import parse_explanation
from .router import parse_time_window
from .rule_first import (
    ANCHORS_PER_FINDING,
    RuleAnswer,
    ToolOutcome,
    _Cites,
    _clock,
    _error_reason,
    _label,
    _low_inputs,
    _plain,
)

log = logging.getLogger(__name__)
SCENE_LIMIT = 10
HONESTY = (
    "Excluded means: some account in the text places this person elsewhere at that time; it is "
    "testimony, not proof. Not excluded does not mean suspected. No verdict about guilt is made."
)
_NOT_NAMES = {"narrator", "witness", "father", "mother", "speaker", "deceased"}


def open_scenes(path: str) -> SceneIndex:
    """The scenes of `path`; empty when the path is empty or the file is missing. A file that is
    present but not grounded (quote not verbatim, window off) is refused with a warning: an
    unchecked scene must not drive an answer."""
    if not path or not Path(path).exists():
        return SceneIndex()
    try:
        return load_index(path)
    except (ValueError, OSError) as exc:
        log.warning("scenes ignored (%s): %s", path, str(exc).splitlines()[0][:200])
        return SceneIndex()


def is_proper_name(name: str) -> bool:
    """A graph person node that names someone ("Baynes"), not a role or a pronoun-like node
    ("the woman", "the narrator", "The report", "Witness")."""
    n = _plain(name)
    return (
        len(n) >= 3
        and n[0].isupper()
        and not re.match(r"the\b", n, re.I)
        and n.casefold() not in _NOT_NAMES
    )


def story_persons(graph: Any, story: str) -> list[tuple[str, str]]:
    """(id, name) of the proper-named person nodes of a story; [] when the graph cannot list them
    (a fake backend): the tool then takes every person it knows."""
    conn = getattr(graph, "conn", None)
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT id, name FROM g_node WHERE kind='person' AND story=? ORDER BY id", (story,)
    ).fetchall()
    return [(r["id"], r["name"]) for r in rows if r["name"] and is_proper_name(r["name"])]


def _victim_ids(graph: Any, scene: Scene) -> list[str]:
    ids: list[str] = []
    for name in [scene.victim, *scene.victim_aliases]:
        try:
            res = graph.find_entities(name, kind="person", story=scene.story)
        except Exception:  # a lookup failure must not lose the board
            continue
        ids += [n for n in res.seeds if n not in ids]
    return ids


def scene_board_args(graph: Any, scene: Scene | None) -> dict[str, Any] | None:
    """Arguments of the `scene_board` call for a scene, or None when no scene is known."""
    if scene is None:
        return None
    args: dict[str, Any] = {
        "story": scene.story,
        "place": scene.place,
        "window": {
            "story_day": scene.story_day,
            "start_min": scene.start_min,
            "end_min": scene.end_min,
        },
        "victim_ids": _victim_ids(graph, scene),
        "limit": SCENE_LIMIT,
    }
    persons = story_persons(graph, scene.story)
    if persons:
        args["person_ids"] = [i for i, _ in persons][:300]
    return args


def scene_names(graph: Any, outcomes: Sequence[ToolOutcome]) -> dict[str, str]:
    """Display names of the persons and speakers on the board (graph lookup, best effort)."""
    ids: set[str] = set()
    for o in outcomes:
        if o.tool != "scene_board" or o.error:
            continue
        for e in [*(o.payload.get("persons") or []), *(o.payload.get("victims") or [])]:
            ids.add(str(e.get("person_id") or ""))
            ids.update(str(x.get("speaker_id")) for x in e.get("evidence") or [] if x)
    out: dict[str, str] = {}
    for i in ids - {"", "None"}:
        try:
            node = graph.get_node(i)
        except Exception:
            node = None
        if node is not None and node.name:
            out[i] = node.name
    return out


# ---------------------------------------------------------------------------- the template
def _when(ev: Mapping[str, Any]) -> str:
    return _plain(ev.get("time_text") or "").rstrip(" .") or "time not stated"


def _who(ev: Mapping[str, Any], names: Mapping[str, str]) -> str:
    sid = ev.get("speaker_id")
    if ev.get("narrator"):
        return "the narrator"
    return _plain(names.get(str(sid), str(sid))) if sid else "speaker not stated"


def _source(ev: Mapping[str, Any]) -> str:
    if ev.get("curated"):
        return "curated"
    return f"extracted, {ev.get('confidence') or 'unknown'} confidence"


def _cite(c: _Cites, entry: Mapping[str, Any], ev: Mapping[str, Any], what: str) -> str:
    label = _label(entry.get("provenance"))
    exp = parse_explanation(entry.get("explanation"))
    for a in [x for x in (ev.get("anchors") or []) if isinstance(x, dict)][:ANCHORS_PER_FINDING]:
        cite = c.add(
            a, label, rule_id="R1", summary=f"R1 scene board: {what}"[:80], explanation=exp
        )
        if cite:
            return cite
    return "(no citable quote)"


def _ev_text(
    c: _Cites, entry: Mapping[str, Any], ev: Mapping[str, Any], names: Mapping[str, str]
) -> str:
    where = _plain(ev.get("place") or "place not stated")
    return (
        f"{where}, {_when(ev)}. Who says so: {_who(ev, names)}. Source: {_source(ev)} "
        f"{_cite(c, entry, ev, where)}"
    )


def _line(
    i: int,
    name: str,
    entry: Mapping[str, Any],
    names: Mapping[str, str],
    c: _Cites,
) -> list[str]:
    status = entry.get("status")
    evidence = [e for e in (entry.get("evidence") or []) if isinstance(e, dict)]
    if status == "not_excluded":
        n = int(entry.get("placed_events") or 0)
        why = (
            f"{n} placed event{'s' if n != 1 else ''}, none with a day and clock time to compare"
            if n
            else "no placed event for this person in the graph"
        )
        return [f"{i}. {name}: not excluded: no placed event at that time ({why})."]
    label = _label(entry.get("provenance"))
    at = [e for e in evidence if e.get("at_scene")]
    away = [e for e in evidence if not e.get("at_scene")]
    if status == "excluded":
        lines = [f"{i}. {name}: excluded by testimony (label {label})."]
        lines += [f"   Elsewhere: {_ev_text(c, entry, e, names)}" for e in away[:2]]
        if at:
            also = _ev_text(c, entry, at[0], names)
            lines.append(f"   Also, another account places them at the scene: {also}")
    else:
        lines = [f"{i}. {name}: placed at the scene (label {label})."]
        lines += [f"   At the scene: {_ev_text(c, entry, e, names)}" for e in at[:2]]
    if label == "conditional":
        low = _low_inputs(parse_explanation(entry.get("explanation")))
        lines.append(
            "   Conditional because these inputs are low-confidence: "
            f"{'; '.join(low) or 'see the explanation'}."
        )
    else:
        lines.append("   Derived: none of the extracted facts it depends on is low-confidence.")
    return lines


def _victim_lines(
    victims: Sequence[Mapping[str, Any]],
    victim_name: str,
    names: Mapping[str, str],
    c: _Cites,
) -> list[str]:
    decisive = [v for v in victims if v.get("status") != "not_excluded"]
    if not decisive:
        return [f"Victim: {victim_name} (not assessed). No placed event at that time."]
    out: list[str] = []
    for v in decisive[:1]:
        who = _plain(names.get(str(v.get("person_id")), victim_name))
        ev = [e for e in (v.get("evidence") or []) if isinstance(e, dict)]
        at = any(e.get("at_scene") for e in ev)
        away = any(not e.get("at_scene") for e in ev)
        head = (
            "The accounts differ about where they were at that time"
            if at and away
            else "An account places them away from the scene at that time"
            if away
            else "An account places them at the scene at that time"
        )
        items = [f"{_ev_text(c, v, e, names)}" for e in ev[:2]]
        out.append(f"Victim: {who} (not assessed). {head}: " + " | ".join(items))
    return out


def build_scene_answer(
    *,
    scene: Scene,
    anchor: Mapping[str, Any] | None,
    outcomes: Sequence[ToolOutcome],
    names: Mapping[str, str] | None = None,
    min_quote_chars: int = 6,
    other_time: bool = False,
) -> RuleAnswer:
    names = names or {}
    c = _Cites(min_quote_chars)
    o = next(x for x in outcomes if x.tool == "scene_board")
    if o.error:
        text = (
            f"No alibi board could be built for the scene at {scene.place} ({scene.story}): "
            f"{_plain(_error_reason(o))}. No person is reported as excluded or placed."
        )
        return RuleAnswer(text, c.sources, "failed")
    p = o.payload
    persons = [e for e in (p.get("persons") or []) if isinstance(e, dict)]
    cite = None
    if anchor is not None:
        cite = c.add(anchor, "source_text", summary="scene quote (curated)", origin="tool")
    when = _clock(scene.start_min)
    if scene.end_min != scene.start_min:
        when += f"-{_clock(scene.end_min)}"
    src = f" Scene source: {cite}." if cite else ""
    head = (
        f"Alibi board for the scene at {_plain(p.get('place') or scene.place)} ({scene.story}), "
        f"{when} ({scene.time_text}); victim: {scene.victim}.{src} "
        f"The scene is {SCENE_MARK}."
    )
    total = int(p.get("total_persons") or len(persons))
    cnt = p.get("counts") or {}
    ex, pl, ne = (int(cnt.get(k) or 0) for k in ("excluded", "placed", "not_excluded"))
    if not persons:
        text = (
            f"{head}\nThe graph holds no person for this story that the board could check, so "
            "nobody is reported as excluded or placed. This says what the extraction found, not "
            "what the story contains."
        )
        return RuleAnswer(text, c.sources, "empty")
    counts = (
        f"Of {total} persons the graph holds for this story, {ex} "
        f"{'is' if ex == 1 else 'are'} excluded by testimony, {pl} "
        f"{'is' if pl == 1 else 'are'} placed at the scene and {ne} "
        f"{'is' if ne == 1 else 'are'} not excluded; {len(persons)} "
        f"{'is' if len(persons) == 1 else 'are'} shown, persons with a placed event first."
    )
    lines: list[str] = []
    for i, e in enumerate(persons, 1):
        pid = str(e.get("person_id"))
        lines += _line(i, _plain(names.get(pid, pid)), e, names, c)
    tail: list[str] = []
    if ex + pl == 0:
        tail.append(
            "No person is excluded or placed: for none of them does the graph hold a placed event "
            "with a stated day and clock time inside this window, so every 'not excluded' above "
            "only means that the graph is silent."
        )
    victims = [v for v in (p.get("victims") or []) if isinstance(v, dict)]
    tail += _victim_lines(victims, scene.victim, names, c)
    tail.append(HONESTY)
    if other_time:
        tail.append(
            "The question names a different time; the board is for the scene's own time window "
            "above."
        )
    if any(e.get("status") != "not_excluded" for e in persons):
        tail.append("Travel time between places is not modelled.")
    if any(int(e.get("events_without_day") or 0) for e in persons):
        tail.append(
            "Placed events without a stated day cannot be compared with the window and are not "
            "used; the rules never assume a day."
        )
    cur = sum(
        1
        for e in [*persons, *victims]
        for x in e.get("evidence") or []
        if isinstance(x, dict) and x.get("curated")
    )
    if cur:
        tail.append(
            f"Curated: {cur} of the facts above were entered and checked by the team "
            "(AI-assisted, human re-check pending); they are not output of the automatic "
            "extraction."
        )
    if p.get("truncated"):
        tail.append(f"{total - len(persons)} further persons are not listed.")
    return RuleAnswer("\n".join([head, counts, *lines, *tail]), c.sources, "scene")


def answer_for(
    scenes: SceneIndex,
    graph: Any,
    question: str,
    outcomes: Sequence[ToolOutcome],
    min_quote_chars: int = 6,
) -> RuleAnswer | None:
    """The board answer when a `scene_board` outcome is present (and its scene is known), else
    None. Used by the agent in place of the generic rule-first builder."""
    if not any(o.tool == "scene_board" for o in outcomes):
        return None
    scene = scenes.match(question)
    if scene is None:
        return None
    anchor = scenes.anchor(scene)
    asked = parse_time_window(question)
    return build_scene_answer(
        scene=scene,
        anchor=anchor.as_dict() if anchor is not None else None,
        outcomes=outcomes,
        names=scene_names(graph, outcomes),
        min_quote_chars=min_quote_chars,
        other_time=asked is not None and asked[0]["start_min"] % 720 != scene.start_min % 720,
    )
