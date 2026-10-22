from symbolic_helpers import claim, ev, fbase, presence, rel_ev, span

from detective_board.symbolic.api import OrderProp, Verdict, check_claim, scan_claims

V, C, U = Verdict.VIOLATED, Verdict.CONSISTENT, Verdict.UNKNOWN
T = span(1, "21:00", "22:00")
CL = claim("c1", presence("W", "B", T))


def test_r3_01_contradiction():
    f = check_claim(fbase([ev("e1", "W", "D", span(1, "21:30"))], [CL]), "c1")
    assert (f.rule_id, f.verdict, f.reason_code, f.conditional) == (
        "R3",
        V,
        "CLAIM_INCOMPATIBLE_WITH_FACT",
        False,
    )
    assert [x.fact_id for x in f.explanation.facts] == ["c1", "e1"]  # both quotes available
    assert {a.chunk_id for a in f.explanation.anchors} == {"s-c1", "s-e1"}


def test_r3_02_corroborated_at_finer_granularity():
    f = check_claim(fbase([ev("e1", "W", "H", span(1, "21:30"))], [CL]), "c1")
    assert (f.verdict, f.reason_code) == (C, "CLAIM_CORROBORATED")


def test_r3_03_unstructured():
    f = check_claim(fbase([], [claim("c1", None)]), "c1")
    assert (f.verdict, f.reason_code) == (U, "UNSTRUCTURED_CLAIM")
    assert f.explanation.anchors


def test_r3_04_partial_time_in_fact():
    f = check_claim(fbase([ev("e1", "W", "D", span(None, "21:30"))], [CL]), "c1")
    assert f.verdict is U


def test_r3_05_order_claim():
    evs = [ev("e1", "W", "B"), rel_ev("e2", "after", "e1")]  # e1 < e2 established
    bad = claim("c1", OrderProp(before_event_id="e2", after_event_id="e1"))
    ok = claim("c2", OrderProp(before_event_id="e1", after_event_id="e2"))
    none = claim("c3", OrderProp(before_event_id="e1", after_event_id="e9"))
    fb = fbase(evs, [bad, ok, none])
    assert check_claim(fb, "c1").verdict is V
    assert check_claim(fb, "c1").explanation.edges[-1].edge_id == "ord:e1>e2:rel"
    assert check_claim(fb, "c2").verdict is C
    assert check_claim(fb, "c3").verdict is U


def test_r3_06_claim_vs_claim_is_unknown():
    other = claim("c2", presence("W", "D", span(1, "21:30", "21:40")), speaker="T")
    f = check_claim(fbase([], [CL, other]), "c1")
    assert (f.verdict, f.reason_code) == (U, "CLAIM_VS_CLAIM")
    reported = ev("e1", "W", "D", span(1, "21:30"), narrator=False)
    assert check_claim(fbase([reported], [CL]), "c1").reason_code == "CLAIM_VS_CLAIM"


def test_r3_07_low_confidence_fact_is_conditional():
    f = check_claim(fbase([ev("e1", "W", "D", span(1, "21:30"), conf="low")], [CL]), "c1")
    assert (f.verdict, f.reason_code, f.conditional) == (V, "CLAIM_VS_EXTRACTED_EVENT", True)
    assert f.explanation.weak == ["e1"]


def test_r3_08_corroborated_and_contradicted():
    evs = [ev("e1", "W", "H", span(1, "21:10")), ev("e2", "W", "D", span(1, "21:30"))]
    f = check_claim(fbase(evs, [CL]), "c1")
    assert f.verdict is V
    assert [x.fact_id for x in f.explanation.facts] == ["c1", "e1", "e2"]


def test_claim_itself_low_confidence_makes_violation_conditional():
    f = check_claim(
        fbase(
            [ev("e1", "W", "D", span(1, "21:30"))], [claim("c1", presence("W", "B", T), conf="low")]
        ),
        "c1",
    )
    assert f.verdict is V and f.conditional and f.explanation.weak == ["c1"]


def test_unknown_claim_ambiguous_place_and_fact_about_other_person():
    assert check_claim(fbase([]), "nope").reason_code == "UNKNOWN_CLAIM"
    amb = claim("c1", presence("W", "X", T))
    assert check_claim(fbase([ev("e1", "W", "D", span(1, "21:30"))], [amb]), "c1").verdict is U
    assert check_claim(fbase([ev("e1", "H1", "D", span(1, "21:30"))], [CL]), "c1").verdict is U


def test_scan_claims_by_speaker_and_stats():
    fb = fbase([ev("e1", "W", "D", span(1, "21:30"))], [CL, claim("c2", None, speaker="T")])
    rep = scan_claims(fb)
    assert [f.verdict for f in rep.findings] == [V, U]  # violated first
    assert rep.stats["claims_examined"] == 2
    assert [
        f.explanation.subject["claim_id"] for f in scan_claims(fb, speaker_id="T").findings
    ] == ["c2"]
