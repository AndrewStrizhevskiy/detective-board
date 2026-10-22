from symbolic_helpers import ev, fbase, rel_ev, span

from detective_board.symbolic.api import Verdict, find_order_cycles, order_of, timeline

V, C, U = Verdict.VIOLATED, Verdict.CONSISTENT, Verdict.UNKNOWN


def chain3():
    # e2 after e1, e3 after e2
    return [ev("e1", "W", "B"), rel_ev("e2", "after", "e1"), rel_ev("e3", "after", "e2")]


def test_r2_01_transitivity():
    f = order_of(fbase(chain3()), "e1", "e3")
    assert (f.verdict, f.reason_code, f.conditional) == (C, "BEFORE", False)
    assert [str(e.edge_id) for e in f.explanation.edges] == ["ord:e1>e2:rel", "ord:e2>e3:rel"]
    assert [x.fact_id for x in f.explanation.facts] == ["e1", "e2", "e3"]
    g = order_of(fbase(chain3()), "e3", "e1")
    assert (g.verdict, g.reason_code) == (C, "AFTER")


def test_r2_02_three_cycle():
    evs = [rel_ev("e1", "after", "e3"), rel_ev("e2", "after", "e1"), rel_ev("e3", "after", "e2")]
    rep = find_order_cycles(fbase(evs))
    assert len(rep.findings) == 1
    f = rep.findings[0]
    assert (f.verdict, f.reason_code) == (V, "ORDER_CYCLE")
    assert len(f.explanation.edges) == 3
    assert f.explanation.suspects == ["ord:e1>e2:rel", "ord:e2>e3:rel", "ord:e3>e1:rel"]
    assert rep.stats["cycles"] == 1
    assert order_of(fbase(evs), "e1", "e2").reason_code == "CYCLIC"


def test_two_cycle_contradictory_before_and_after():
    evs = [ev("e1", "W", "B"), rel_ev("e2", "after", "e1"), rel_ev("e3", "before", "e2")]
    # e2 after e1 -> e1<e2 ; e3 before e2 -> e3<e2 ; add contradiction e1 before e2 declared on e1 too
    evs[0] = ev("e1", "W", "B", span(None, None, rel="before", ref_event_id="e2"))
    evs = [evs[0], rel_ev("e2", "before", "e1")]
    rep = find_order_cycles(fbase(evs))
    assert len(rep.findings) == 1 and len(rep.findings[0].explanation.edges) == 2


def test_r2_03_self_loop():
    rep = find_order_cycles(fbase([rel_ev("e1", "after", "e1")]))
    assert [f.verdict for f in rep.findings] == [V]
    assert len(rep.findings[0].explanation.edges) == 1
    assert order_of(fbase([rel_ev("e1", "after", "e1")]), "e1", "e1").reason_code == "CYCLIC"


def test_same_event_without_loop_is_unknown():
    f = order_of(fbase(chain3()), "e1", "e1")
    assert (f.verdict, f.reason_code) == (U, "SAME_EVENT")


def test_r2_04_overlapping_spans_not_ordered():
    fb = fbase(
        [
            ev("e1", "W", "B", span(1, "21:00", "22:00")),
            ev("e2", "W", "D", span(1, "21:00", "22:00")),
        ]
    )
    assert order_of(fb, "e1", "e2").reason_code == "NO_PATH"
    assert find_order_cycles(fb).findings == []


def test_r2_05_touching_not_ordered_and_r2_06_gap_ordered():
    touch = fbase(
        [
            ev("e1", "W", "B", span(1, "21:00", "22:00")),
            ev("e2", "W", "D", span(1, "22:00", "23:00")),
        ]
    )
    f = order_of(touch, "e1", "e2")
    assert (f.verdict, f.reason_code) == (U, "NO_PATH")
    gap = fbase(
        [
            ev("e1", "W", "B", span(1, "21:00", "22:00")),
            ev("e2", "W", "D", span(1, "22:01", "23:00")),
        ]
    )
    g = order_of(gap, "e1", "e2")
    assert (g.verdict, g.reason_code) == (C, "BEFORE")
    assert [str(e.edge_id) for e in g.explanation.edges] == ["ord:e1>e2:time"]
    assert g.explanation.anchors  # union of both events' anchors


def test_r2_07_relation_contradicts_times():
    fb = fbase(
        [
            ev("e1", "W", "B", span(2, "08:00")),
            ev("e2", "W", "D", span(1, "10:00", rel="after", ref_event_id="e1")),
        ]
    )
    rep = find_order_cycles(fb)
    assert len(rep.findings) == 1
    f = rep.findings[0]
    assert f.verdict is V
    assert f.explanation.suspects == ["ord:e1>e2:rel"]


def test_r2_08_low_confidence_edge_is_conditional_suspect():
    evs = [
        rel_ev("e1", "after", "e3"),
        rel_ev("e2", "after", "e1", tconf="low"),
        rel_ev("e3", "after", "e2"),
    ]
    f = find_order_cycles(fbase(evs)).findings[0]
    assert f.verdict is V and f.conditional
    assert f.explanation.weak == ["ord:e1>e2:rel"]
    assert f.explanation.suspects[0] == "ord:e1>e2:rel"


def test_r2_09_disconnected():
    f = order_of(fbase([ev("e1", "W", "B"), ev("e2", "W", "D")]), "e1", "e2")
    assert (f.verdict, f.reason_code) == (U, "NO_PATH")
    assert f.explanation.missing == ["order_path:e1->e2"]


def test_r2_10_text_position_is_not_time():
    # events listed e2 before e1 in input, no time info at all
    f = order_of(fbase([ev("e2", "W", "D"), ev("e1", "W", "B")]), "e1", "e2")
    assert f.reason_code == "NO_PATH"


def test_empty_graph_and_unknown_event_and_unresolved_ref():
    assert find_order_cycles(fbase([])).findings == []
    assert order_of(fbase([]), "a", "b").reason_code == "UNKNOWN_EVENT"
    rep = find_order_cycles(fbase([rel_ev("e2", "after", "ghost")]))
    assert rep.findings == [] and rep.stats["unresolved_refs"] == 1
    f = order_of(fbase([rel_ev("e2", "after", "ghost"), ev("e1", "W", "B")]), "e1", "e2")
    assert "resolvable_ref:e2" in f.explanation.missing


def test_duplicate_edges_and_during_gives_no_edge():
    evs = [
        ev("e1", "W", "B", span(1, "08:00", "09:00")),
        ev("e2", "W", "B", span(1, "10:00", "11:00", rel="after", ref_event_id="e1")),
        rel_ev("e3", "during", "e1"),
    ]
    f = order_of(fbase(evs), "e1", "e2")
    assert f.verdict is C and [str(e.edge_id) for e in f.explanation.edges] == ["ord:e1>e2:rel"]
    assert order_of(fbase(evs), "e1", "e3").reason_code == "NO_PATH"


def test_partial_time_orders_only_via_relative_edges():
    fb = fbase([ev("e1", "W", "B", span(None, "09:00")), ev("e2", "W", "B", span(None, "10:00"))])
    assert order_of(fb, "e1", "e2").reason_code == "NO_PATH"


def test_cycle_scan_restricted_to_event_ids():
    evs = [rel_ev("e1", "after", "e2"), rel_ev("e2", "after", "e1"), rel_ev("e3", "after", "e3")]
    assert len(find_order_cycles(fbase(evs)).findings) == 2
    assert len(find_order_cycles(fbase(evs), event_ids=["e3"]).findings) == 1


def test_timeline_orders_dated_events_and_filters():
    fb = fbase(
        [
            ev("e3", "W", "D", span(2, "08:00")),
            ev("e1", "W", "H", span(1, "09:00", "10:00")),
            ev("e2", "H1", "B", span(1, "08:00")),
            ev("e4", "W", "B", None),
        ]
    )
    assert [f.fact_id for f in timeline(fb)] == ["e2", "e1", "e3"]
    assert [f.fact_id for f in timeline(fb, include_undated=True)] == ["e2", "e1", "e3", "e4"]
    assert [f.fact_id for f in timeline(fb, person_id="W")] == ["e1", "e3"]
    assert [f.fact_id for f in timeline(fb, place_id="B")] == ["e2", "e1"]  # H is inside B
    assert len(timeline(fb, limit=1)) == 1
