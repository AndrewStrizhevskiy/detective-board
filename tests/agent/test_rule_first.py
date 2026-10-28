"""Rule-first answers: contradiction / alibi questions are answered by a deterministic template
built from the rule result. The model is never called on these routes (FakeLLM.calls == [])."""

import json
import re
from pathlib import Path

import pytest

from detective_board.agent import AgentConfig, FakeLLM
from detective_board.agent.answer import CITATION, self_check
from detective_board.agent.honesty import asserts_consistency
from detective_board.agent.rule_first import coverage_for
from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.api.fixture import boscombe_explanation
from detective_board.extract import normalise
from detective_board.extract.schema_v2 import Entity, Event, Extraction
from detective_board.graph import ChunkRef, GraphStore
from detective_board.retrieval import Hit
from detective_board.symbolic.api import Verdict

from .conftest import FakeRetriever, FakeTools, hit, make_agent, types
from .test_graph_route import QUESTION, T1, T2, S, _graph

CHUNKS = Path(__file__).resolve().parents[2] / "data" / "chunks.jsonl"
GARCIA_Q = (
    "Is there a conflict about where Aloysius Garcia was at about one o'clock on the night he died?"
)
HONEST = "The rule engine found no violation among the facts extracted for wisteria-lodge. "


def prose(text: str) -> str:
    """The answer without its quoted source text."""
    return CITATION.sub("", text)


def run_rf(g, question=QUESTION, hits=None, llm=None, tools=None, **cfg):
    llm = llm or FakeLLM("MODEL TEXT MUST NOT APPEAR")
    cfg.setdefault("answer_mode", "generate")  # the old empty-result template; see test_extractive
    retr = FakeRetriever(hits or [hit(1, T1, story=S), hit(2, T2, story=S)])
    agent = make_agent(
        llm, retr, graph=g, tools=tools or InProcessRulesClient(g), config=AgentConfig(**cfg)
    )
    return list(agent.ask(question)), llm


# ---- (a) findings ---------------------------------------------------------
def test_findings_template_has_one_sentence_per_finding_and_verbatim_quotes():
    ev, llm = run_rf(_graph())
    assert llm.calls == []
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    assert fin.answer.startswith("Rule engine result for wl: 1 finding.")
    assert "R1 reports verdict violated (OVERLAP_DIFFERENT_PLACES), label conditional" in fin.answer
    assert "Conditional because these inputs are low-confidence:" in fin.answer
    assert {c.quote for c in fin.citations} == {
        "Some time later Garcia looked in at my door",
        "He had been there on Oxshott Common since one o'clock",
    }
    assert all(c.label == "conditional" for c in fin.citations)
    for c in fin.citations:  # anchors point at the real text
        chunk = {"wl-0001": T1, "wl-0002": T2}[c.anchor.chunk_id]
        base = {"wl-0001": 1000, "wl-0002": 2000}[c.anchor.chunk_id]
        assert chunk[c.anchor.char_start - base : c.anchor.char_end - base] == c.quote
    lab = fin.provenance
    assert lab and all(p.rule_id == "R1" and p.explanation is not None for p in lab)
    # the Explanation is the tool's own
    res = next(e for e in ev if e.type == "tool_result")
    assert lab[0].explanation == res.explanation
    assert not asserts_consistency(prose(fin.answer))


def test_event_sequence_matches_an_llm_run():
    ev, _ = run_rf(_graph())
    t = types(ev)
    assert t[0] == "route_decided"
    order = [
        "retrieval_started",
        "retrieval_results",
        "graph_query",
        "graph_results",
        "tool_call",
        "tool_result",
        "enriched_query",
        "answer_token",
        "citation_check",
        "final",
    ]
    assert [x for x in dict.fromkeys(t) if x in order] == order
    assert t[-2:] == ["citation_check", "final"]
    eq = next(e for e in ev if e.type == "enriched_query")
    assert "rule-first" in eq.strategy and eq.prompt_chars == 0 and eq.rule_facts == 2
    chk = next(e for e in ev if e.type == "citation_check")
    assert chk.ok and chk.action == "accept"
    assert chk.citations and all(c.verbatim and c.source_exists for c in chk.citations)
    toks = [e.text for e in ev if e.type == "answer_token"]
    assert len(toks) > 10 and "".join(toks) == ev[-1].answer
    assert [e.seq for e in ev] == list(range(len(ev)))


def test_run_is_deterministic():
    a, _ = run_rf(_graph())
    b, _ = run_rf(_graph())
    assert [e.model_dump_json() for e in a] == [e.model_dump_json() for e in b]


def test_template_passes_the_same_self_check_without_help():
    ev, _ = run_rf(_graph())
    eq = next(e for e in ev if e.type == "enriched_query")
    assert eq.sources  # sources and answer are consistent with the stream
    json.dumps([e.model_dump(mode="json") for e in ev])


def test_derived_r3_finding_from_the_boscombe_fixture():
    exp = boscombe_explanation().model_dump(mode="json")
    payload = {
        "status": "ok",
        "findings": [
            {
                "rule": "R3",
                "reason_code": exp["reason_code"],
                "provenance": "derived",
                "explanation": exp,
                "anchors": exp["anchors"],
            }
        ],
    }
    tools = FakeTools(payload)
    llm = FakeLLM("MODEL TEXT MUST NOT APPEAR")
    agent = make_agent(llm, tools=tools)
    ev = list(agent.ask("Are there contradictions in the Speckled Band story?"))
    assert llm.calls == [] and tools.calls[0][0] == "find_contradictions"
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    assert "R3 reports verdict violated (CLAIM_INCOMPATIBLE_WITH_FACT), label derived" in fin.answer
    assert "Derived:" in fin.answer and "Conditional" not in fin.answer
    assert {c.label for c in fin.citations} == {"derived"}
    assert len(fin.citations) == 2
    (lab, *_) = fin.provenance
    assert lab.explanation is not None and lab.explanation.model_dump(mode="json") == exp
    assert "no explanation" not in fin.answer


def test_many_findings_are_counted_and_capped():
    exp = boscombe_explanation().model_dump(mode="json")
    one = {
        "rule": "R3",
        "reason_code": "X",
        "provenance": "derived",
        "explanation": exp,
        "anchors": exp["anchors"],
    }
    tools = FakeTools({"status": "ok", "findings": [one] * 6, "truncated": True})
    ev = list(make_agent(FakeLLM("x"), tools=tools).ask("Any contradictions in Speckled Band?"))
    ans = ev[-1].answer
    assert "6 findings. The first 4 are shown." in ans and ans.count("reports verdict") == 4
    assert "truncated its list" in ans


# ---- (b) no findings ------------------------------------------------------
def _real_chunk(cid):
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d["chunk_id"] == cid:
            return d
    raise KeyError(cid)


def _garcia_graph() -> GraphStore:
    """Wisteria Lodge as the real extraction left it: Garcia and his events have clock times
    ('nearly one', 'valid up to one') but no story day, so R1 cannot compare any pair."""
    c6, c15 = _real_chunk("wisteria-lodge-0006"), _real_chunk("wisteria-lodge-0015")
    ref = lambda d: ChunkRef(d["chunk_id"], d["story"], d["char_start"], d["char_end"], d["text"])  # noqa: E731
    g = GraphStore()
    g.ingest_many(
        [
            (
                ref(c6),
                Extraction(
                    entities=[
                        Entity(name="Garcia", type="person", quote="Garcia"),
                        Entity(name="Scott Eccles", type="person", quote="my door"),
                        Entity(name="Wisteria Lodge", type="place", quote="Wisteria Lodge"),
                    ],
                    events=[
                        Event(
                            description="Garcia looks in at the door",
                            time_text="nearly one o’clock",
                            place="Wisteria Lodge",
                            participants=["Garcia"],
                            quote="Some time later Garcia looked in at my door",
                        ),
                        Event(
                            description="Eccles wakes",
                            time_text="nearly nine",
                            participants=["Scott Eccles"],
                            quote="the time was nearly nine",
                        ),
                    ],
                ),
            ),
            (
                ref(c15),
                Extraction(
                    entities=[
                        Entity(name="Oxshott", type="place", quote="Oxshott"),
                        Entity(name="Garcia", type="person", quote="Garcia"),
                    ],
                    events=[
                        Event(
                            description="Garcia walks towards Oxshott",
                            time_text="up to one o’clock",
                            place="Oxshott",
                            participants=["Garcia"],
                            quote="Garcia was walking in that direction",
                        )
                    ],
                ),
            ),
        ]
    )
    normalise.apply(g, "wisteria-lodge")
    return g


def _real_hits():
    out = []
    for i, cid in enumerate(("wisteria-lodge-0006", "wisteria-lodge-0015", "wisteria-lodge-0013")):
        d = _real_chunk(cid)
        out.append(
            Hit(
                cid, d["story"], d["char_start"], d["char_end"], 0.03 - i * 0.001, {}, {}, d["text"]
            )
        )
    return out


def test_garcia_regression_honest_answer_instead_of_no_conflict():
    """Observed 2026-10-26: rule result empty, the 4B model answered 'There is no conflict ...'
    and the self-check passed. The answer is now the fixed honest template."""
    g = _garcia_graph()
    llm = FakeLLM('There is no conflict about where Aloysius Garcia was. [1: "nearly one o’clock"]')
    ev, llm = run_rf(g, GARCIA_Q, hits=_real_hits(), llm=llm)
    assert llm.calls == []  # not even asked
    assert ev[0].tools == ["find_contradictions"]
    res = next(e for e in ev if e.type == "tool_result")
    assert res.ok and res.summary == "status=ok items=0"
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    assert fin.answer.startswith(HONEST + "This does not show that the accounts are consistent: ")
    assert (
        "the graph holds 3 events and 0 claims for this story; 2 events have an exact clock time, "
        "0 have a story day, and 0 claims carry a presence proposition; rule R1 examined 1 event "
        "pairs and could not decide 1 of them."
    ) in fin.answer
    assert (
        "have a story day" in fin.answer and "0 claims carry a presence proposition" in fin.answer
    )
    assert "no conflict" not in fin.answer.lower() and "no contradiction" not in fin.answer.lower()
    assert not asserts_consistency(prose(fin.answer))
    assert "Text passages that may be relevant (not rule results):" in fin.answer
    assert 1 <= len(fin.citations) <= 3
    assert {c.label for c in fin.citations} == {"source_text"}
    assert all(p.label == "source_text" and p.explanation is None for p in fin.provenance)
    chunk = {h.chunk_id: h for h in _real_hits()}
    for c in fin.citations:  # verbatim in the real text, at the reported offsets
        h = chunk[c.anchor.chunk_id]
        assert (
            h.text[c.anchor.char_start - h.char_start : c.anchor.char_end - h.char_start] == c.quote
        )
    print("\nGARCIA ANSWER:\n" + fin.answer)


def test_coverage_counts_come_from_the_fact_source():
    g = _graph()
    cov = coverage_for(InProcessRulesClient(g), g, S)
    assert cov is not None and (cov.events, cov.claims) == (2, 0)
    assert (cov.exact_times, cov.story_days, cov.presence_props) == (2, 2, 0)
    assert (cov.pairs, cov.undecided) == (1, 0)  # one decided pair: that is the finding
    assert coverage_for(None, None, S) is None and coverage_for(None, g, None) is None
    assert coverage_for(None, g, S) == cov  # falls back to the graph store itself


def test_empty_without_passages_still_honest():
    g = _garcia_graph()
    ev, llm = run_rf(
        g, GARCIA_Q, hits=[hit(1, "Nothing relevant here at all.", story="wisteria-lodge")]
    )
    fin = ev[-1]
    assert fin.status == "answered" and llm.calls == []
    assert fin.answer.startswith(HONEST) and "Text passages" not in fin.answer
    assert fin.citations == []


def test_alibi_unknown_is_reported_as_unknown_not_as_agreement():
    g = _garcia_graph()
    ev, llm = run_rf(g, "Where was Garcia at one o'clock? Check his alibi.", hits=_real_hits())
    fin = ev[-1]
    assert llm.calls == []
    res = next(e for e in ev if e.type == "tool_result" and e.tool == "check_alibi")
    assert res.ok
    assert fin.answer.startswith("The rule engine found no violation")
    assert "check_alibi returned verdict unknown" in fin.answer
    assert not asserts_consistency(prose(fin.answer))


def test_alibi_supported_uses_the_verdict_the_rule_returned():
    payload = {"status": "supported", "provenance": "derived", "reason_code": "ALIBI_SUPPORTED"}
    exp = boscombe_explanation().model_copy(
        update={"rule_id": "R1", "reason_code": "ALIBI_SUPPORTED", "verdict": Verdict.CONSISTENT}
    )
    payload["explanation"] = exp.model_dump(mode="json")
    tools = FakeTools(payload)
    agent = make_agent(FakeLLM("x"), graph=_graph(), tools=tools)
    ev = list(agent.ask("Where was Garcia at 9 pm? Check his alibi"))
    fin = ev[-1]
    assert "R1 reports verdict consistent (ALIBI_SUPPORTED)" in fin.answer


# ---- (c) errors, ambiguity ------------------------------------------------
def test_tool_error_falls_through_to_the_text_path():
    """A tool that failed says nothing about the question: no rule-first template."""
    tools = FakeTools({"error": {"code": "timeout", "message": "x"}})
    llm = FakeLLM('The man looked in at the door. [1: "Some time later Garcia looked in"]')
    ev, llm = run_rf(_graph(), tools=tools, llm=llm)
    fin = ev[-1]
    assert llm.calls and fin.status == "answered"
    assert "could not answer this question" not in fin.answer
    eq = next(e for e in ev if e.type == "enriched_query")
    assert "rule-first" not in eq.strategy
    assert not asserts_consistency(prose(fin.answer))


def test_tool_error_without_any_retrieval_is_a_tool_error_refusal():
    tools = FakeTools({"error": {"code": "timeout", "message": "x"}})
    agent = make_agent(FakeLLM("x"), FakeRetriever([]), tools=tools)
    ev = list(agent.ask("Any contradictions in Holmes?"))
    assert ev[-1].status == "refused" and ev[-1].refusal_code == "tool_error"


def test_no_tool_client_falls_through_to_the_text_path():
    llm = FakeLLM('The band was a snake. [1: "a deadly snake from India"]')
    agent = make_agent(llm)
    ev = list(agent.ask("Are there contradictions in the Speckled Band story?"))
    assert llm.calls and ev[-1].status == "answered"
    assert "rule-first" not in next(e for e in ev if e.type == "enriched_query").strategy


def test_ambiguous_person_alibi_lists_the_candidates():
    g = _graph(cousins=True)
    ev, llm = run_rf(g, "Where was Moreno at one o'clock? Check the alibi.")
    fin = ev[-1]
    assert llm.calls == [] and fin.status == "answered"
    assert "check_alibi was not run: name 'Moreno' is ambiguous" in fin.answer
    assert "Ana Moreno (wl)" in fin.answer and "Lucas Moreno (wl)" in fin.answer
    assert fin.answer.count("is ambiguous") == 1


def test_ambiguous_person_contradiction_scan_notes_it():
    g = _graph(cousins=True)
    ev, llm = run_rf(g, "Is there a conflict about where Moreno was at one o'clock?")
    fin = ev[-1]
    assert llm.calls == []
    assert "Note: name 'Moreno' is ambiguous: Ana Moreno (wl), Lucas Moreno (wl)" in fin.answer
    assert "the scan covered the whole story" in fin.answer


def test_widened_scope_is_said():
    g = _graph(cousins=True)  # Ana Moreno neither takes part in an event nor speaks
    ev, llm = run_rf(g, "Is there a conflict in what Ana Moreno said?")
    fin = ev[-1]
    assert llm.calls == []
    assert "has no events of their own" in fin.answer and "whole story" in fin.answer


# ---- switch and guards ----------------------------------------------------
def test_switch_off_restores_the_llm_path():
    llm = FakeLLM('Garcia looked in at the door. [1: "Some time later Garcia looked in"]')
    ev, llm = run_rf(_graph(), llm=llm, rule_first=False)
    assert llm.calls and "enriched_query" in types(ev)
    assert "rule-first" not in next(e for e in ev if e.type == "enriched_query").strategy


def test_other_routes_keep_the_llm_path():
    llm = FakeLLM('The band was a snake. [1: "a deadly snake from India"]')
    agent = make_agent(llm)
    ev = list(agent.ask("What was the speckled band?"))
    assert llm.calls and ev[-1].status == "answered"


def test_llm_path_rejects_consistency_claims_on_an_empty_rule_result():
    """rule_first off: the guard in the self-check rejects 'no conflict' and sends a hint."""
    bad = 'There is no conflict about where Garcia was. [1: "Some time later Garcia looked in at my door"]'
    ok = 'Garcia looked in at the door. [1: "Some time later Garcia looked in at my door"]'
    llm = FakeLLM([bad, ok])
    g = _garcia_graph()
    c6 = _real_chunk("wisteria-lodge-0006")
    h = Hit(c6["chunk_id"], c6["story"], c6["char_start"], c6["char_end"], 0.03, {}, {}, c6["text"])
    agent = make_agent(
        llm,
        FakeRetriever([h]),
        graph=g,
        tools=InProcessRulesClient(g),
        config=AgentConfig(rule_first=False, answer_mode="generate"),
    )
    ev = list(agent.ask(GARCIA_Q))
    checks = [e for e in ev if e.type == "citation_check"]
    assert [c.ok for c in checks] == [False, True] and checks[0].action == "retry"
    assert any("rule result is empty or failed" in p for p in checks[0].problems)
    assert "rule result is empty or failed" in llm.calls[1][1]["content"]
    assert "no conflict" not in ev[-1].answer and ev[-1].status == "answered"


_TOOL = re.compile(r"n=(\d+) [^>\n]*origin=tool[^>\n]*>>>\n(.*?)\n<<<END", re.S)


def test_llm_path_guard_lets_a_real_verdict_through_and_blocks_a_failed_tool():
    g = _graph()
    cites = lambda m: " ".join(f'[{n}: "{t}"]' for n, t in _TOOL.findall(m[-1]["content"]))  # noqa: E731
    ev, _ = run_rf(
        g, llm=FakeLLM(lambda m: "Garcia was at two places. " + cites(m)), rule_first=False
    )
    assert ev[-1].status == "answered"  # a real finding: no guard
    tools = FakeTools({"error": {"code": "timeout", "message": "x"}})
    msg = 'There is no conflict. [1: "Some time later Garcia looked in at my door"]'
    ev2, _ = run_rf(g, llm=FakeLLM(msg), tools=tools, rule_first=False)
    assert ev2[-1].status != "answered" and "no conflict" not in ev2[-1].answer.lower()


@pytest.mark.parametrize(
    "text, flagged",
    [
        ("There is no conflict about where he was.", True),
        ("No contradiction was found.", True),
        ("His account is consistent with the other.", True),
        ("The accounts do not conflict.", True),
        ("Both stories agree.", True),
        ("This does not show that the accounts are consistent: coverage is thin.", False),
        ("The rule engine found no violation among the facts.", False),
        ("R1 reports verdict violated (OVERLAP_DIFFERENT_PLACES).", False),
        ("An inconsistent account.", False),
    ],
)
def test_asserts_consistency_detector(text, flagged):
    assert bool(asserts_consistency(text)) is flagged


def test_self_check_flags_but_template_helper_allows_uncited():
    from detective_board.agent.context import Source

    s = [Source(1, "c", "s", 0, 20, "Garcia looked in", "vector", "source_text")]
    plain = self_check('Garcia looked in. [1: "Garcia looked in"]', s)
    assert plain.ok
    blocked = self_check('No conflict here. [1: "Garcia looked in"]', s, forbid_consistency=True)
    assert not blocked.ok and any("rule result is empty" in p for p in blocked.problems)
    assert not self_check("Statement of the engine.", s).ok
    assert self_check("Statement of the engine.", s, allow_uncited=True).ok
    bad = self_check('Engine. [1: "invented words"]', s, allow_uncited=True)
    assert not bad.ok  # a quote that is present is always verified


# ---- (e) chronology: build_timeline template --------------------------------
TL_Q = "Give the timeline of the night Aloysius Garcia died"


def _ev(eid, desc, quote, base, text, when=None, **kw):
    a = text.index(quote)
    return {
        "event_id": eid,
        "description": desc,
        "when": when,
        "place_id": None,
        "participants": [],
        "anchors": [
            {
                "story": S,
                "chunk_id": "wl-0001" if base == 1000 else "wl-0002",
                "char_start": base + a,
                "char_end": base + a + len(quote),
                "quote": quote,
            }
        ],
    } | kw


def _tl_payload(**kw):
    when = {"story_day": 1, "start_min": 780, "end_min": 780, "confidence": "high"}
    p = {
        "status": "ok",
        "events": [
            _ev(
                "e1", "Garcia looked in at the door", "Garcia looked in at my door", 1000, T1, when
            ),
            _ev("e2", "Baynes says he was on the Common", "since one o'clock", 2000, T2),
            _ev("e3", "Garcia was seen at the Lodge", "Wisteria Lodge", 1000, T1, curated=True),
        ],
        "undated_count": 2,
        "total_events": 3,
        "truncated": False,
        "provenance": "derived",
        "rule_id": "R2",
    }
    return p | kw


def run_tl(payload, question=TL_Q, **kw):
    llm = FakeLLM("MODEL TEXT MUST NOT APPEAR")
    retr = FakeRetriever([hit(1, T1, story=S), hit(2, T2, story=S)])
    tools = FakeTools(payload)
    agent = make_agent(llm, retr, tools=tools, config=AgentConfig(**kw))
    return list(agent.ask(question)), llm, tools


def test_timeline_template_lists_dated_then_undated_with_quotes():
    ev, llm, tools = run_tl(_tl_payload())
    assert llm.calls == []
    tool, args = tools.calls[0]
    assert tool == "build_timeline"
    assert args["include_undated"] is True and 10 <= args["limit"] <= 15 and args["story"] == S
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    lines = fin.answer.splitlines()
    assert lines[0].startswith(
        "Timeline for wl: the graph holds 3 events (1 with a stated day and time"
    )
    assert "3 are shown." in lines[0]
    assert lines[1].startswith("1. day key 1, 13:00 (derived): Garcia looked in at the door [1: ")
    assert lines[2].startswith("2. time not stated (derived): Baynes says")
    assert lines[3].startswith("3. time not stated (curated): Garcia was seen")
    assert (
        "Dated events are ordered by the time stated in the text; the others follow in order"
        in (fin.answer)
    )
    assert "which is not necessarily the order in which they happened." in fin.answer
    assert "correct order" not in fin.answer
    assert "Curated: 1 of the events" in fin.answer
    assert not asserts_consistency(prose(fin.answer))
    assert [c.quote for c in fin.citations][0] == "Garcia looked in at my door"
    assert next(e for e in ev if e.type == "enriched_query").strategy.startswith(
        "rule-first (timeline)"
    )


def test_timeline_truncated_and_conditional_label():
    ev, _, _ = run_tl(
        _tl_payload(truncated=True, total_events=40, undated_count=38, provenance="conditional")
    )
    a = ev[-1].answer
    assert (
        "holds 40 events (2 with a stated day and time, 38 without); 3 are shown, the rest were cut"
        in a
    )
    assert "(conditional)" in a


def test_timeline_only_undated_says_so():
    p = _tl_payload()
    p["events"] = [e | {"when": None} for e in p["events"]]
    a = run_tl(p)[0][-1].answer
    assert "None of the events shown has both a stated day and time" in a


def test_timeline_empty_reports_missing_and_invents_nothing():
    ev, llm, _ = run_tl(
        {"status": "insufficient_evidence", "events": [], "undated_count": 0, "total_events": 0}
    )
    fin = ev[-1]
    assert llm.calls == [] and fin.status == "answered"
    assert fin.answer.startswith("The graph holds no events for wl")
    assert "no order of events is reported" in fin.answer
    assert not asserts_consistency(prose(fin.answer))
    assert not re.search(r"^\d+\. ", fin.answer, re.M)


def test_timeline_tool_error_goes_to_text_path_not_template():
    ev, llm, _ = run_tl(
        {"error": {"code": "timeout", "message": "x"}},
        "Give the timeline: Garcia looked in at my door at Wisteria Lodge",
        answer_mode="generate",
    )
    assert "Timeline for" not in ev[-1].answer
    assert llm.calls  # a failed tool says nothing; the normal text path answers


def test_timeline_build_answer_error_text():
    from detective_board.agent.rule_first import ToolOutcome, build_timeline_answer

    out = [ToolOutcome("build_timeline", {"error": {"code": "timeout", "message": "x"}})]
    ans = build_timeline_answer(story=S, outcomes=out, link=None, notes=[])
    assert ans.kind == "failed" and "could not be built" in ans.text
    assert "nothing is said about their order" in ans.text


def test_timeline_with_graph_scopes_person_and_story():
    g = _graph()
    tools = FakeTools(_tl_payload())
    ev, llm = run_rf(g, "Give the timeline of the night Garcia died", tools=tools)
    assert llm.calls == []
    _, args = tools.calls[0]
    assert args["story"] == S and args["person_id"].endswith("garcia")
    assert args["include_undated"] is True
    assert ev[-1].answer.startswith("Timeline for Garcia in wl: ")


def test_timeline_day_wording_dates_keys_and_partial_times():
    from datetime import date as _d

    from detective_board.agent.rule_first import _when_text

    jun3 = _d(2001, 6, 3).toordinal()
    w = {"story_day": jun3, "start_min": 900, "end_min": 900, "confidence": "high"}
    assert _when_text(w) == ("June 3 (date in the text), 15:00", False)
    w = {"story_day": 20162, "start_min": 60, "end_min": 120, "confidence": "low"}
    assert _when_text(w) == ("day key 20162, 01:00-02:00 (time uncertain)", True)
    w = {"story_day": None, "start_min": 360, "end_min": 720, "confidence": "high"}
    assert _when_text(w)[0] == "06:00-12:00, day not stated"
    assert _when_text(None) == (None, False)
