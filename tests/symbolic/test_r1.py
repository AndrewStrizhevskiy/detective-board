import pytest
from symbolic_helpers import ev, fbase, rel_ev, span

from detective_board.symbolic.api import (
    Verdict,
    check_presence,
    scan_presence_conflicts,
)

V, C, U = Verdict.VIOLATED, Verdict.CONSISTENT, Verdict.UNKNOWN


def _w_b():
    return ev("e1", "W", "B", span(1, "21:00", "22:00"))


# (id, events, verdict, reason_code, conditional, weak)
ROWS = [
    (
        "R1-01",
        [_w_b(), ev("e2", "W", "D", span(1, "21:30", "22:30"))],
        V,
        "OVERLAP_DIFFERENT_PLACES",
        False,
        [],
    ),
    (
        "R1-02",
        [_w_b(), ev("e2", "W", "D", span(1, "22:00", "23:00"))],
        C,
        "TIME_DISJOINT",
        False,
        [],
    ),
    (
        "R1-03",
        [ev("e1", "W", "B", span(1, "21:00")), ev("e2", "W", "D", span(1, "21:00"))],
        V,
        "OVERLAP_DIFFERENT_PLACES",
        False,
        [],
    ),
    (
        "R1-04",
        [ev("e1", "W", "B", span(1, "21:00")), ev("e2", "W", "D", span(1, "21:01"))],
        C,
        "TIME_DISJOINT",
        False,
        [],
    ),
    (
        "R1-05",
        [_w_b(), ev("e2", "W", "H", span(1, "21:30", "22:30"))],
        C,
        "PLACE_COMPATIBLE",
        False,
        [],
    ),
    (
        "R1-06",
        [_w_b(), ev("e2", "W", "D", span(None, "21:30", "22:30"))],
        U,
        "TIME_UNDECIDED",
        False,
        [],
    ),
    (
        "R1-07",
        [
            ev("e1", "W", "B", span(1, "18:00", "22:00", exact=False)),
            ev("e2", "W", "D", span(1, "20:00", "21:00")),
        ],
        U,
        "TIME_UNDECIDED",
        False,
        [],
    ),
    (
        "R1-08",
        [
            ev("e1", "W", "B", span(1, "06:00", "12:00", exact=False)),
            ev("e2", "W", "D", span(1, "20:00", "21:00")),
        ],
        C,
        "TIME_DISJOINT",
        False,
        [],
    ),
    (
        "R1-09",
        [_w_b(), ev("e2", "W", "X", span(1, "21:00", "22:00"))],
        U,
        "PLACE_UNRESOLVED",
        False,
        [],
    ),
    (
        "R1-10",
        [
            _w_b(),
            ev(
                "e2",
                "W",
                "D",
                span(None, "06:00", "12:00", exact=False, rel="after", ref_event_id="e0"),
            ),
            ev("e0", "Z", "L", span(None, None)),
        ],
        U,
        "TIME_UNDECIDED",
        False,
        [],
    ),
    (
        "R1-11",
        [_w_b(), ev("e2", "W", "D", span(1, "21:30", "22:30"), conf="low")],
        V,
        "OVERLAP_DIFFERENT_PLACES",
        True,
        ["e2"],
    ),
]


@pytest.mark.parametrize(
    "rid,events,verdict,reason,conditional,weak", ROWS, ids=[r[0] for r in ROWS]
)
def test_r1_table(rid, events, verdict, reason, conditional, weak):
    rep = scan_presence_conflicts(fbase(events), person_id="W", include_consistent=True)
    assert len(rep.findings) == 1, rep.stats
    f = rep.findings[0]
    assert (f.rule_id, f.verdict, f.reason_code, f.conditional) == (
        "R1",
        verdict,
        reason,
        conditional,
    )
    assert f.provenance == "derived"
    assert f.explanation.weak == weak
    assert f.explanation.subject == {"person_id": "W"}


def test_r1_01_overlap_derivation_and_ids():
    f = scan_presence_conflicts(
        fbase([_w_b(), ev("e2", "W", "D", span(1, "21:30", "22:30"))])
    ).findings[0]
    assert [x.fact_id for x in f.explanation.facts] == ["e1", "e2"]
    assert [str(x.edge_id) for x in f.explanation.edges] == [
        "OCCURRED_AT:e1:B",
        "OCCURRED_AT:e2:D",
        "PARTICIPATED_IN:W:e1",
        "PARTICIPATED_IN:W:e2",
    ]
    assert f.explanation.derivation[0].output == "overlap [d1 21:30,d1 22:00)"
    assert f.explanation.derivation[1].output == "DISTINCT"


def test_r1_07_possible_overlap_listed_by_default():
    fb = fbase(
        [
            ev("e1", "W", "B", span(1, "18:00", "22:00", exact=False)),
            ev("e2", "W", "D", span(1, "20:00", "21:00")),
        ]
    )
    rep = scan_presence_conflicts(fb)  # default: violated + unknown with possible_overlap
    assert [f.reason_code for f in rep.findings] == ["TIME_UNDECIDED"]
    assert "possible_overlap" in rep.findings[0].explanation.notes
    assert rep.findings[0].explanation.missing == ["exact_time:e1"]


def test_r1_default_hides_other_unknown_and_consistent():
    fb = fbase([_w_b(), ev("e2", "W", "D", span(None, "21:30", "22:30"))])
    rep = scan_presence_conflicts(fb)
    assert rep.findings == []
    assert rep.stats["unknown"] == 1 and rep.stats["pairs_examined"] == 1


def test_r1_12_same_occurrence_guard():
    fb = fbase(
        [
            ev("e1", "W", "B", span(1, "21:00", "22:00"), occurrence_id="occ"),
            ev("e2", "W", "D", span(1, "21:00", "22:00"), occurrence_id="occ"),
        ]
    )
    rep = scan_presence_conflicts(fb, include_consistent=True)
    assert rep.findings == [] and rep.stats["skipped_same_occurrence"] == 1


def test_r1_13_different_persons():
    fb = fbase([_w_b(), ev("e2", "H1", "D", span(1, "21:00", "22:00"))])
    rep = scan_presence_conflicts(fb, include_consistent=True)
    assert rep.findings == [] and rep.stats["pairs_examined"] == 0


def test_r1_14_missing_place_not_examined():
    fb = fbase([_w_b(), ev("e2", "W", None, span(1, "21:30"))])
    rep = scan_presence_conflicts(fb, include_consistent=True)
    assert rep.findings == [] and rep.stats["skipped_no_place"] == 1


def test_event_with_two_participants_pairs_each_person():
    fb = fbase(
        [
            ev("e1", ["W", "H1"], "B", span(1, "21:00", "22:00")),
            ev("e2", ["W", "H1"], "D", span(1, "21:00", "22:00")),
        ]
    )
    rep = scan_presence_conflicts(fb)
    assert sorted(f.explanation.subject["person_id"] for f in rep.findings) == ["H1", "W"]


def test_skipped_no_time():
    fb = fbase([_w_b(), ev("e2", "W", "D", None), ev("e3", "W", "D", span(None, None))])
    rep = scan_presence_conflicts(fb, include_consistent=True)
    assert rep.stats["skipped_no_time"] == 2 and rep.stats["pairs_examined"] == 0


def test_motion_verb_makes_finding_conditional():
    fb = fbase([_w_b(), ev("e2", "W", "D", span(1, "21:30", "22:30"), desc="Went to the docks")])
    f = scan_presence_conflicts(fb).findings[0]
    assert f.verdict is V and f.conditional and f.explanation.weak == ["e2"]


def test_low_time_confidence_makes_finding_conditional():
    fb = fbase([_w_b(), ev("e2", "W", "D", span(1, "21:30", "22:30", conf="low"))])
    f = scan_presence_conflicts(fb).findings[0]
    assert f.conditional and f.explanation.weak == ["e2"]


def test_same_place_twice_and_identical_intervals_and_nesting():
    same = fbase([_w_b(), ev("e2", "W", "B", span(1, "21:00", "22:00"))])
    assert (
        scan_presence_conflicts(same, include_consistent=True).findings[0].reason_code
        == "PLACE_COMPATIBLE"
    )
    ident = fbase([_w_b(), ev("e2", "W", "D", span(1, "21:00", "22:00"))])
    assert scan_presence_conflicts(ident).findings[0].verdict is V
    nested = fbase([_w_b(), ev("e2", "W", "D", span(1, "21:15", "21:45"))])
    assert scan_presence_conflicts(nested).findings[0].verdict is V


def test_different_story_days_are_disjoint():
    fb = fbase([_w_b(), ev("e2", "W", "D", span(2, "21:00", "22:00"))])
    assert (
        scan_presence_conflicts(fb, include_consistent=True).findings[0].reason_code
        == "TIME_DISJOINT"
    )


def test_alias_resolution_same_place_by_surface_form():
    fb = fbase([_w_b(), ev("e2", "W", "baker  St", span(1, "21:00", "22:00"))])
    assert (
        scan_presence_conflicts(fb, include_consistent=True).findings[0].reason_code
        == "PLACE_COMPATIBLE"
    )


def test_unknown_place_ref_is_unresolved_not_distinct():
    fb = fbase([_w_b(), ev("e2", "W", "the club", span(1, "21:00", "22:00"))])
    assert (
        scan_presence_conflicts(fb, include_consistent=True).findings[0].reason_code
        == "PLACE_UNRESOLVED"
    )


def test_granularity_chain_and_sibling_rooms():
    from detective_board.symbolic.api import PlaceRec

    pl = [
        PlaceRec(id="Lon", name="London"),
        PlaceRec(id="Bk", name="Baker Street", parent_id="Lon"),
        PlaceRec(id="221", name="221B", parent_id="Bk"),
        PlaceRec(id="r1", name="sitting room", parent_id="221"),
        PlaceRec(id="r2", name="bedroom", parent_id="221"),
    ]
    t = span(1, "21:00", "22:00")
    deep = fbase([ev("a", "W", "Lon", t), ev("b", "W", "r1", t)], pl=pl)
    assert (
        scan_presence_conflicts(deep, include_consistent=True).findings[0].reason_code
        == "PLACE_COMPATIBLE"
    )
    sib = fbase([ev("a", "W", "r1", t), ev("b", "W", "r2", t)], pl=pl)
    assert scan_presence_conflicts(sib).findings[0].verdict is V


def test_parent_cycle_in_places_terminates():
    from detective_board.symbolic.api import PlaceRec

    pl = [
        PlaceRec(id="a", name="A", parent_id="b"),
        PlaceRec(id="b", name="B", parent_id="a"),
        PlaceRec(id="c", name="C"),
    ]
    t = span(1, "21:00", "22:00")
    fb = fbase([ev("e1", "W", "a", t), ev("e2", "W", "c", t)], pl=pl)
    assert scan_presence_conflicts(fb).findings[0].verdict is V


def test_empty_graph_and_max_findings():
    rep = scan_presence_conflicts(fbase([]), include_consistent=True)
    assert rep.findings == [] and rep.stats["pairs_examined"] == 0
    evs = [ev(f"e{i}", "W", p, span(1, "21:00", "22:00")) for i, p in enumerate("BDX") if p != "X"]
    evs.append(ev("e9", "W", "L", span(1, "21:00", "22:00")))
    assert len(scan_presence_conflicts(fbase(evs), max_findings=1).findings) == 1


# --- check_presence (alibi) ---

W_WIN = span(1, "21:15", "21:45")


def test_r1_15_alibi_contradicted():
    f = check_presence(
        fbase([ev("e1", "W", "D", span(1, "21:00", "22:00"))]),
        person_id="W",
        window=W_WIN,
        place_id="B",
    )
    assert (f.verdict, f.reason_code, f.conditional) == (V, "ALIBI_CONTRADICTED", False)
    assert [x.fact_id for x in f.explanation.facts] == ["e1"]


def test_r1_16_contradictory_data_not_hidden():
    fb = fbase(
        [
            ev("e1", "W", "B", span(1, "21:00", "22:00")),
            ev("e2", "W", "D", span(1, "21:00", "22:00")),
        ]
    )
    f = check_presence(fb, person_id="W", window=W_WIN, place_id="B")
    assert f.verdict is V
    assert [x.fact_id for x in f.explanation.facts] == ["e1", "e2"]


def test_alibi_supported_and_granularity():
    fb = fbase([ev("e1", "W", "H", span(1, "21:00", "22:00"))])
    f = check_presence(fb, person_id="W", window=W_WIN, place_id="B")
    assert (f.verdict, f.reason_code) == (C, "ALIBI_SUPPORTED")


def test_alibi_unknown_cases():
    none = check_presence(fbase([]), person_id="W", window=W_WIN, place_id="B")
    assert (none.verdict, none.reason_code) == (U, "NO_DATED_EVENTS")
    fuzzy = check_presence(
        fbase([ev("e1", "W", "D", span(1, "21:00", "22:00"))]),
        person_id="W",
        window=span(1, "21:15", "21:45", exact=False),
        place_id="B",
    )
    assert (fuzzy.verdict, fuzzy.reason_code) == (U, "NO_DECISIVE_EVIDENCE")
    amb = check_presence(fbase([]), person_id="W", window=W_WIN, place_id="X")
    assert amb.reason_code == "PLACE_UNRESOLVED"
    disjoint = check_presence(
        fbase([ev("e1", "W", "D", span(1, "23:00", "23:30"))]),
        person_id="W",
        window=W_WIN,
        place_id="B",
    )
    assert disjoint.verdict is U


def test_alibi_low_confidence_is_conditional():
    f = check_presence(
        fbase([ev("e1", "W", "D", span(1, "21:00", "22:00"), conf="low")]),
        person_id="W",
        window=W_WIN,
        place_id="B",
    )
    assert f.verdict is V and f.conditional and f.explanation.weak == ["e1"]


def test_rel_ev_helper_is_not_a_presence():
    fb = fbase([rel_ev("e2", "after", "e1")])
    assert scan_presence_conflicts(fb, include_consistent=True).findings == []
