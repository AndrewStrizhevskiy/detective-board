import itertools
import random
from pathlib import Path

import pytest
from symbolic_helpers import CHUNKS, claim, ev, fbase, presence, rel_ev, span

from detective_board.symbolic.api import FactBase, OrderProp, Verdict, run_all

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "symbolic" / "holmes_mini.json"


def rich_events():
    return [
        ev("e1", "W", "B", span(1, "21:00", "22:00")),
        ev("e2", "W", "D", span(1, "21:30", "22:30"), conf="low"),
        ev("e3", ["W", "H1"], "H", span(1, "21:15")),
        ev("e4", "H1", "X", span(1, "21:00", "22:00")),
        ev("e5", "W", "L", span(None, "21:00")),
        ev("e6", "W", "D", span(2, "08:00")),
        rel_ev("e7", "after", "e6"),
        rel_ev("e8", "after", "e8"),
        rel_ev("e9", "after", "e10"),
        rel_ev("e10", "after", "e9", tconf="low"),
    ]


def rich_fb() -> FactBase:
    claims = [
        claim("c1", presence("W", "B", span(1, "21:00", "22:00"))),
        claim("c2", OrderProp(before_event_id="e7", after_event_id="e6")),
        claim("c3", None),
    ]
    return fbase(rich_events(), claims)


def dump(fb: FactBase) -> list[str]:
    return [r.model_dump_json() for r in run_all(fb)]


def test_determinism_twice_and_shuffled_byte_identical():
    base = dump(rich_fb())
    assert dump(rich_fb()) == base
    events, claims = rich_events(), rich_fb().claims
    for seed in range(5):
        rnd = random.Random(seed)
        rnd.shuffle(events)
        shuffled = fbase(events, list(reversed(claims)), pl=list(reversed(rich_fb().places)))
        assert dump(shuffled) == base
        assert shuffled.digest() == rich_fb().digest()


def test_digest_changes_with_facts():
    a = rich_fb()
    b = fbase([*rich_events(), ev("e11", "W", "B", span(3, "10:00"))], a.claims)
    assert a.digest() != b.digest()


def test_fixture_file_roundtrip_and_determinism():
    fb = FactBase.model_validate_json(FIXTURE.read_text())
    first, second = dump(fb), dump(FactBase.model_validate_json(FIXTURE.read_text()))
    assert first == second
    verdicts = {f.explanation.verdict for r in run_all(fb) for f in r.findings}
    assert Verdict.VIOLATED in verdicts


def all_findings(fb, **kw):
    from detective_board.symbolic.api import find_order_cycles, scan_claims, scan_presence_conflicts

    out = scan_presence_conflicts(fb, include_consistent=True).findings
    out += find_order_cycles(fb).findings + scan_claims(fb).findings
    return out


def test_every_violated_or_consistent_finding_has_anchored_explanation():
    checked = 0
    for f in all_findings(rich_fb()):
        if f.verdict is Verdict.UNKNOWN:
            continue
        ex = f.explanation
        assert (
            ex.rule_id == f.rule_id and ex.verdict == f.verdict and ex.conditional == f.conditional
        )
        assert ex.facts and ex.derivation and ex.anchors
        assert [x.fact_id for x in ex.facts] == sorted(x.fact_id for x in ex.facts)
        for item in (*ex.facts, *ex.edges):
            assert item.anchors, item
        for a in ex.anchors:
            assert a.quote
            assert CHUNKS[a.chunk_id][a.rel_start : a.rel_end] == a.quote
        assert ex.anchors == sorted(
            ex.anchors,
            key=lambda a: (a.story, a.char_start, a.char_end, a.chunk_id, a.quote),
        )
        assert f.finding_id.startswith(f.rule_id + ":")
        checked += 1
    assert checked >= 6


def test_findings_are_sorted_and_json_serialisable():
    for rep in run_all(rich_fb()):
        keys = [
            (f.rule_id, ["violated", "unknown", "consistent"].index(f.verdict.value), f.finding_id)
            for f in rep.findings
        ]
        assert keys == sorted(keys)
        assert rep.model_dump_json()
        assert all(isinstance(v, int) for v in rep.stats.values())


def test_all_empty_graph():
    for rep in run_all(fbase([])):
        assert rep.findings == []


def test_run_all_rejects_unknown_rule():
    with pytest.raises(ValueError):
        run_all(fbase([]), ("R9",))


def test_unknown_findings_never_conditional_and_have_missing():
    for f in all_findings(rich_fb()):
        if f.verdict is Verdict.UNKNOWN:
            assert not f.conditional and f.explanation.weak == []
            assert f.explanation.missing or f.reason_code in {"SAME_EVENT", "CLAIM_VS_CLAIM"}


def test_permutations_of_pair_input_give_same_finding():
    evs = [
        ev("e1", "W", "B", span(1, "21:00", "22:00")),
        ev("e2", "W", "D", span(1, "21:30", "22:30")),
    ]
    outs = {dump(fbase(list(p)))[0] for p in itertools.permutations(evs)}
    assert len(outs) == 1
