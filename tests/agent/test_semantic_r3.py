"""Neuro-symbolic R3: candidate pairing on a hand-built graph, the judge with a fake LLM, the
wiring behind the `semantic_r3` switch and the honesty wording. No Ollama."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from detective_board.agent import AgentConfig, FakeLLM
from detective_board.agent.honesty import asserts_consistency
from detective_board.agent.rule_first import RuleAnswer
from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.agent.semantic_r3 import (
    BLOCK_TITLE,
    JUDGE_SCHEMA,
    JUDGE_SYSTEM_PROMPT,
    JUDGE_VERSION,
    Judged,
    Outcome,
    candidate_pairs,
    find_candidates,
    judge_messages,
    judge_pair,
    load_statements,
    parse_verdict,
    render_block,
)
from detective_board.extract.schema_v2 import Claim, Entity, Extraction
from detective_board.graph import ChunkRef, GraphStore

from .conftest import FakeRetriever, hit, make_agent

S = "wl"
T1 = "Eccles said: Garcia looked in at my bedroom door and it was nearly one o'clock at night."
T2 = "Baynes said: Garcia lay dead on the Common since one o'clock, before the rain."
T3 = "Lestrade said: the weather was cold and the tea was served in the garden at noon."
Q1 = "Garcia looked in at my bedroom door and it was nearly one o'clock at night"
Q2 = "Garcia lay dead on the Common since one o'clock, before the rain"
Q3 = "the weather was cold and the tea was served in the garden at noon"
QUESTION = "Is there a conflict about where Garcia was at one o'clock?"


def _graph() -> GraphStore:
    g = GraphStore()
    rows = [
        (1, T1, "Eccles", Q1),
        (2, T2, "Baynes", Q2),
        (3, T3, "Lestrade", Q3),
    ]
    items = []
    for n, text, who, quote in rows:
        ref = ChunkRef(f"{S}-{n:04d}", S, 1000 * n, 1000 * n + len(text), text)
        ents = [Entity(name=who, type="person", quote=who)]
        if n == 1:
            ents.append(Entity(name="Garcia", type="person", quote="Garcia"))
        items.append(
            (
                ref,
                Extraction(
                    entities=ents,
                    claims=[Claim(speaker=who, content=quote, quote=quote)],
                ),
            )
        )
    g.ingest_many(items)
    return g


def _verdict(v: str) -> str:
    return json.dumps({"verdict": v})


# ---- candidate pairs -------------------------------------------------------
def test_pairs_link_different_speakers_on_shared_words_and_skip_unrelated():
    g = _graph()
    sts = load_statements(g.conn, S)
    assert {s.speaker for s in sts} == {"Eccles", "Baynes", "Lestrade"}
    pairs = candidate_pairs(sts)
    assert [(p.a.speaker, p.b.speaker) for p in pairs] == [("Eccles", "Baynes")] or {
        p.a.speaker for p in pairs
    } | {p.b.speaker for p in pairs} == {"Eccles", "Baynes"}
    assert "clock" in pairs[0].shared and all(p.a.speaker != p.b.speaker for p in pairs)


def test_pairs_are_deterministic_capped_and_respect_the_person_filter():
    g = _graph()
    sts = load_statements(g.conn, S)
    assert candidate_pairs(sts) == candidate_pairs(list(reversed(sts)))
    assert candidate_pairs(sts, max_pairs=0) == []
    eccles = next(s.speaker_id for s in sts if s.speaker == "Eccles")
    lest = next(s.speaker_id for s in sts if s.speaker == "Lestrade")
    assert len(candidate_pairs(sts, persons=[eccles])) == 1
    assert candidate_pairs(sts, persons=[lest]) == []


def test_same_speaker_never_pairs():
    g = GraphStore()
    t = "Eccles said Garcia came at one o'clock. Eccles said Garcia left at one o'clock."
    ref = ChunkRef(f"{S}-0001", S, 0, len(t), t)
    a, b = "Garcia came at one o'clock", "Garcia left at one o'clock"
    g.ingest(
        ref,
        Extraction(
            entities=[Entity(name="Eccles", type="person", quote="Eccles")],
            claims=[
                Claim(speaker="Eccles", content=a, quote=a),
                Claim(speaker="Eccles", content=b, quote=b),
            ],
        ),
    )
    assert candidate_pairs(load_statements(g.conn, S)) == []


# ---- the judge -------------------------------------------------------------
def test_judge_parses_valid_invalid_and_empty_answers():
    assert parse_verdict(_verdict("contradicts")) == "contradicts"
    assert parse_verdict(_verdict("consistent")) == "consistent"
    assert parse_verdict('{"verdict": "maybe"}') is None
    assert parse_verdict("contradicts") is None
    assert parse_verdict("") is None
    assert parse_verdict('{"other": 1}') is None
    assert parse_verdict("[1]") is None


def test_judge_prompt_has_a_static_prefix_and_both_quotes():
    pair = candidate_pairs(load_statements(_graph().conn, S))[0]
    llm = FakeLLM(_verdict("contradicts"))
    j = judge_pair(llm, pair)
    assert j.verdict == "contradicts"
    msgs = llm.calls[0]
    assert msgs[0] == {"role": "system", "content": JUDGE_SYSTEM_PROMPT}
    assert Q1 in msgs[1]["content"] and Q2 in msgs[1]["content"]
    assert "Eccles" in msgs[1]["content"] and "Baynes" in msgs[1]["content"]
    assert llm.formats[0] == JUDGE_SCHEMA and JUDGE_SCHEMA["properties"]["verdict"]["enum"]
    assert judge_messages(pair)[0] == judge_messages(pair)[0]
    assert JUDGE_VERSION == "R3J-2"


def test_find_candidates_survives_a_bad_model_and_a_failing_model():
    g = _graph()
    out = find_candidates(FakeLLM("not json"), g.conn, S)
    assert out.judged and out.judged[0].verdict is None and not out.contradicting

    def boom(_m):
        raise OSError("down")

    out = find_candidates(FakeLLM(boom), g.conn, S)
    assert out.error and "could not be reached" in out.error and out.judged == []


# ---- wording ---------------------------------------------------------------
def _ans() -> RuleAnswer:
    return RuleAnswer("The rule engine found no violation among the facts. ", [], "empty")


def test_block_shows_two_quotes_and_never_claims_proof_or_agreement():
    g = _graph()
    out = find_candidates(FakeLLM(_verdict("contradicts")), g.conn, S)
    res = render_block(out, _ans())
    assert BLOCK_TITLE in res.text and "hypothesis" in res.text.lower()
    assert "judged by a small model, not proven" in res.text
    assert f'"{Q1}"' in res.text and f'"{Q2}"' in res.text
    assert [s.label for s in res.sources] == ["conditional", "conditional"]
    low = res.text.lower()
    assert "proves" not in low and "consistent" not in low
    assert not asserts_consistency(res.text.split(BLOCK_TITLE)[1].split('["')[0])


def test_block_shows_at_most_the_configured_number_of_pairs():
    st = load_statements(_graph().conn, S)
    pair = candidate_pairs(st)[0]
    out = Outcome([Judged(pair, "contradicts")] * 3)
    assert render_block(out, _ans(), show=2).text.count("- Hypothesis ") == 2


def test_empty_block_says_it_does_not_show_consistency():
    out = find_candidates(FakeLLM(_verdict("unrelated")), _graph().conn, S)
    t = render_block(out, _ans()).text
    assert "none was judged as contradicting" in t
    assert "does not show that the accounts are consistent" in t
    assert not asserts_consistency(t.split(BLOCK_TITLE)[1])


def test_failed_model_is_reported_not_hidden():
    t = render_block(Outcome([], "the model could not be reached (OSError)"), _ans()).text
    assert "did not complete" in t and "could not be reached" in t


# ---- wiring ----------------------------------------------------------------
def _run(on: bool, answer_mode: str, llm=None):
    g = _graph()
    llm = llm or FakeLLM(
        lambda m: _verdict("contradicts") if "Statement A" in m[-1]["content"] else ""
    )
    retr = FakeRetriever([hit(1, T1, story=S), hit(2, T2, story=S)])
    cfg = AgentConfig(answer_mode=answer_mode, semantic_r3=on)
    agent = make_agent(llm, retr, graph=g, tools=InProcessRulesClient(g), config=cfg)
    return list(agent.ask(QUESTION)), llm


def test_switch_defaults_to_off():
    assert AgentConfig().semantic_r3 is False


@pytest.mark.parametrize("mode", ["generate", "extractive"])
def test_switch_off_changes_nothing(mode):
    ev, llm = _run(False, mode)
    fin = ev[-1]
    assert BLOCK_TITLE not in fin.answer
    assert not any(c and "Statement A" in c[-1]["content"] for c in llm.calls)


def test_switch_on_adds_a_separate_block_after_the_rule_line():
    ev, llm = _run(True, "generate")
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    head, _, block = fin.answer.partition(BLOCK_TITLE)
    assert head.startswith("The rule engine found no violation") and "hypothesis" in block
    assert f'"{Q1}"' in block and f'"{Q2}"' in block
    assert {c.label for c in fin.citations if c.quote in (Q1, Q2)} <= {"conditional"}
    assert "rule-first (empty)" in next(e for e in ev if e.type == "enriched_query").strategy
    assert not asserts_consistency(block.split('["')[0])


def test_switch_on_in_the_extractive_path_keeps_the_block_before_the_text_answer():
    ev, _ = _run(True, "extractive")
    assert BLOCK_TITLE in ev[-1].answer


def test_switch_on_but_other_question_kind_is_untouched():
    g = _graph()
    llm = FakeLLM("")
    retr = FakeRetriever([hit(1, T1, story=S)])
    agent = make_agent(
        llm, retr, graph=g, tools=InProcessRulesClient(g), config=AgentConfig(semantic_r3=True)
    )
    ev = list(agent.ask("Who is Garcia?"))
    assert BLOCK_TITLE not in ev[-1].answer


# ---- the eval guard --------------------------------------------------------
def _r3_eval():
    root = Path(__file__).resolve().parents[2]
    for p in (root / "src", root / "eval"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    if "r3_semantic" in sys.modules:
        return sys.modules["r3_semantic"]
    spec = importlib.util.spec_from_file_location("r3_semantic", root / "eval" / "r3_semantic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r3_semantic"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_eval_refuses_test_ids_and_loads_only_dev_cases():
    R = _r3_eval()
    split = R._split()
    with pytest.raises(SystemExit):
        R.refuse_test_ids([split["test"][0]])
    with pytest.raises(SystemExit):
        R.dev_cases([split["dev"][0], split["test"][1]])
    with pytest.raises(SystemExit):
        R.refuse_test_ids(["c999"])
    cases = R.dev_cases()
    assert sorted(c["id"] for c in cases) == sorted(split["dev"]) and len(cases) == 23
    assert not {c["id"] for c in cases} & set(split["test"])
