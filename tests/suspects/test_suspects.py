import importlib.util
import json
import sqlite3
from pathlib import Path

from detective_board.extract.llm import FakeClient
from detective_board.suspects import NO_PERSON, matrix
from detective_board.suspects.candidates import (
    build_candidates,
    labels,
    mask_candidates,
    mask_text,
)
from detective_board.suspects.cards import Card, cards_for_chunk, ground_cards, vote
from detective_board.suspects.common import KV, Chunk, load_cases, load_split, wilson, window_around

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("suspects_run", ROOT / "eval" / "suspects_run.py")
run = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(run)  # type: ignore[union-attr]


def make_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """create table g_chunk (chunk_id text primary key, story text, char_start int, char_end int);
        create table g_node (id text primary key, kind text, story text, name text, unnamed int default 0);
        create table g_mention (id integer primary key, node_id text, chunk_id text, surface text, role text);"""
    )
    db.executemany(
        "insert into g_chunk values (?,?,?,?)", [("s-0", "s", 0, 100), ("s-1", "s", 100, 900)]
    )
    people = [("p1", "Sherlock Holmes"), ("p2", "Mr. John Turner"), ("p3", "Turner"),
              ("p4", "James McCarthy"), ("p5", "Charles McCarthy"), ("p6", "Witness"),
              ("p7", "Late Arrival")]  # fmt: skip
    for pid, name in people:
        db.execute(
            "insert into g_node (id, kind, story, name) values (?, 'person', 's', ?)", (pid, name)
        )
    ms = [("p1", "s-0", "Holmes"), ("p2", "s-0", "Mr. John Turner"), ("p3", "s-0", "Turner"),
          ("p3", "s-0", "Turner"), ("p4", "s-0", "James McCarthy"), ("p5", "s-0", "Charles McCarthy"),
          ("p6", "s-0", "Witness"), ("p7", "s-1", "Late Arrival")]  # fmt: skip
    for nid, ch, surf in ms:
        db.execute(
            "insert into g_mention (node_id, chunk_id, surface, role) values (?,?,?, 'name')",
            (nid, ch, surf),
        )
    return db


def test_candidates_filter_merge_and_cut() -> None:
    cs = build_candidates(make_db(), "s", 200, "Who killed Charles McCarthy?")
    names = [c.name for c in cs]
    assert "Sherlock Holmes" not in names and "Witness" not in names  # detective, role word
    assert "Charles McCarthy" not in names  # the victim of the question
    assert "Late Arrival" not in names  # mentioned only after the cut
    assert "Turner" not in names and "Mr. John Turner" in names  # bare surname merged
    turner = next(c for c in cs if c.name == "Mr. John Turner")
    assert turner.mentions == 3 and "Turner" in turner.surfaces
    assert "James McCarthy" in names


def test_masking_replaces_every_form() -> None:
    cs = build_candidates(make_db(), "s", 200, "Who killed Charles McCarthy?")
    mask_candidates(cs)
    text = "Mr. John Turner met James McCarthy. Turner left."
    masked = mask_text(text, cs)
    assert "Turner" not in masked and "McCarthy" not in masked
    assert labels(cs)[-1] == NO_PERSON and all(
        label.startswith("Person-") for label in labels(cs)[:-1]
    )


def test_ground_cards_requires_verbatim_quote_and_nearby_name() -> None:
    cs = build_candidates(make_db(), "s", 200, "Q?")
    mask_candidates(cs)
    turner = next(c for c in cs if "Turner" in c.name)
    text = "He was calm. Person-A hated the old man. Nobody saw him that night."
    turner.label = "Person-A"
    chunk = Chunk("s-0", 0, 100, text)
    ok = {
        "candidate": "Person-A",
        "effect": "points_to",
        "kind": "motive",
        "quote": "Person-A hated the old man.",
    }
    fake_quote = dict(ok, quote="Person-A wanted him dead.")
    far = dict(
        ok, candidate="Person-A", quote="He was calm."
    )  # name is in the next sentence: allowed
    unknown = dict(ok, candidate="Person-Z")
    bad_effect = dict(ok, effect="guilty")
    got = ground_cards([ok, fake_quote, far, unknown, bad_effect], chunk, text, cs)
    assert [c.quote for c in got] == ["Person-A hated the old man.", "He was calm."]


def test_vote_needs_majority() -> None:
    a = Card("c", "X", "points_to", "motive", "q1")
    b = Card("c", "Y", "clears", "alibi", "q2")
    kept = vote([[a, b], [a], [a]])
    assert [(c.candidate, c.effect) for c in kept] == [("X", "points_to")]


def test_cards_for_chunk_uses_cache(tmp_path) -> None:
    cs = build_candidates(make_db(), "s", 200, "Q?")
    chunk = Chunk("s-0", 0, 100, "Mr. John Turner hated the old man. He said so.")
    reply = json.dumps({"cards": [{"candidate": "Mr. John Turner", "effect": "points_to", "kind": "motive",
                                   "quote": "Mr. John Turner hated the old man."}]})  # fmt: skip
    client = FakeClient(lambda prompt: reply)
    cache = KV(tmp_path / "c.sqlite")
    kw = dict(model="m", question="Q?", cands=cs, chunk=chunk, masked=False, samples=1)
    cards, st = cards_for_chunk(client, cache, **kw)  # type: ignore[arg-type]
    assert len(cards) == 1 and st["calls"] == 1
    cards2, st2 = cards_for_chunk(client, cache, **kw)  # type: ignore[arg-type]
    assert cards2 == cards and st2["cached"] == 1 and len(client.calls) == 1


def test_matrix_ranks_abstains_and_labels_hypothesis() -> None:
    def card(ch, cand, eff="points_to", kind="motive"):
        return Card(ch, cand, eff, kind, "q")

    cards = [card("c1", "A"), card("c2", "A", kind="means"), card("c3", "A"), card("c1", "B"),
             card("c2", "B", "clears", "alibi")]  # fmt: skip
    v = matrix.build(cards, ["A", "B", NO_PERSON])
    assert v.rows[0].candidate == "A" and v.top == "A" and v.label == "hypothesis" and not v.abstain
    weak = matrix.build([card("c1", "A")], ["A", "B"])
    assert weak.abstain and weak.top is None
    close = matrix.build(
        [card("c1", "A"), card("c2", "A"), card("c1", "B"), card("c2", "B")], ["A", "B"]
    )
    assert close.abstain  # the lead over the runner-up is below the margin


def test_judge_outcomes() -> None:
    case = {
        "culprit_kind": "human",
        "culprit_names": ["John Turner"],
        "cleared_names": ["James McCarthy"],
    }
    assert run.judge(case, "Mr. John Turner") == "correct"
    assert run.judge(case, "young McCarthy") == "other_wrong"  # not in the cleared list as written
    assert run.judge(case, "James McCarthy") == "cleared_accused"
    assert run.judge(case, None) == "abstain" and run.judge(case, NO_PERSON) == "other_wrong"
    nh = {"culprit_kind": "non_human", "culprit_names": ["the horse"], "cleared_names": ["Simpson"]}
    assert (
        run.judge(nh, NO_PERSON) == "correct"
        and run.judge(nh, "Fitzroy Simpson") == "cleared_accused"
    )


def test_cases_and_split_are_consistent() -> None:
    cases, split = load_cases(), load_split()
    stories = {c["story"] for c in cases}
    assert len(cases) == 16 and set(split["dev"]) | set(split["test"]) == stories
    assert not set(split["dev"]) & set(split["test"])
    for c in cases:
        assert 0 < c["cut_char"] < len((ROOT / "data" / "clean" / f"{c['story']}.txt").read_text())
        assert c["culprit_kind"] in ("human", "non_human") and c["culprit_names"]


def test_wilson_and_window() -> None:
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(3, 8)
    assert 0.1 < lo < 0.375 < hi < 0.7
    t = "One. Two two. Three."
    assert window_around(t, 5, 9, around=1) == "One. Two two. Three."
