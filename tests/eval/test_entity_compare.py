"""Entity-answer comparison script: the 'wrong person' metric, the pairing and the unchanged check
on hand-made rows (no Ollama)."""

from .conftest import load

C = load("entity_compare")
CASE = {"culprit_names": [["Cairns"], ["Patrick Cairns"]], "cleared_names": ["Neligan"]}


def row(i, outcome, answer, strategy="", innocent=False):
    return {
        "id": i,
        "condition": "full",
        "outcome": outcome,
        "answer": answer,
        "strategy": strategy,
        "innocent_accused": innocent,
    }


def test_wrong_person_only_counts_the_entity_line():
    r = row("a", "named", 'From the sources: [1: "x"]\nThe text names Patrick Cairns here.')
    assert C.named_person(r) == "Patrick Cairns" and not C.wrong_person(r, CASE)
    w = row("a", "wrong", 'From the sources: [1: "x"]\nThe text names Silas Brown here.')
    assert C.wrong_person(w, CASE)
    assert not C.wrong_person(row("a", "wrong", 'From the sources: [1: "Brown"]'), CASE)


def test_compare_pairs_and_unchanged():
    off = {
        ("a", "full"): row("a", "wrong", "quote"),
        ("b", "full"): row("b", "wrong", "same"),
        ("c", "full"): row("c", "wrong", "quote"),
    }
    on = {
        ("a", "full"): row("a", "named", "q\nThe text names Cairns here.", "entity choice (v3)"),
        ("b", "full"): row("b", "wrong", "same"),
        ("c", "full"): row("c", "refused", "nothing", "entity choice (v3)"),
    }
    cases = {k[0]: CASE for k in off}
    res = C.compare(off, on, cases)
    assert res["arms"]["on"]["named"]["k"] == 1 and res["arms"]["off"]["named"]["k"] == 0
    assert res["paired"]["named"]["only_b"] == 1 and res["paired"]["named"]["only_a"] == 0
    assert res["paired"]["refused"]["only_b"] == 1
    assert C.unchanged(off, on) == ["b"]
    assert "switch on" in C.render(res, off, on, "t")
