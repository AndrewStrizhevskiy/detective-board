import json
from pathlib import Path

from detective_board.agent import AgentConfig
from detective_board.agent.answer import leaks_reasoning, self_check, strip_reasoning
from detective_board.agent.context import (
    Source,
    build_messages,
    estimate_tokens,
    fit_prompt,
    sources_from_hits,
)
from detective_board.agent.window import best_window, sentence_spans

from .conftest import FakeLLM, FakeRetriever, hit, make_agent

ROOT = Path(__file__).resolve().parents[2]
FILLER = "The fog lay thick over the quiet street and nobody passed along it. "
ANSWER = "It was a swamp adder, the deadliest snake in India. "
FIRST = "Mist hid the Surrey lane from every watcher. "
LONG = FIRST + FILLER * 12 + ANSWER + FILLER * 12


def test_sentences_keep_exact_offsets_and_abbreviations():
    t = 'Dr. Watson came in. "Where?" said Holmes. He left at 9 A. M. sharp. End.'
    spans = sentence_spans(t)
    assert [t[a:b] for a, b in spans] == [
        "Dr. Watson came in.",
        '"Where?" said Holmes.',
        "He left at 9 A. M. sharp.",
        "End.",
    ]


def test_window_picks_answer_sentence_and_maps_back():
    w = best_window(LONG, "What kind of snake was it, the swamp adder?", 60)
    assert "swamp adder" in LONG[w.start : w.end]
    assert LONG[w.start : w.end].strip()[-1] in ".!?"  # never cut mid-sentence
    assert len(LONG[w.start : w.end].split()) <= 60 * 1.2
    assert w.start > 0 and w.end < len(LONG)
    h = hit(3, LONG)
    s = sources_from_hits([h], "What kind of snake was it?", 60)[0]
    assert s.window == LONG[s.win_start : s.win_end]
    assert h.text[s.win_start : s.window_end] == s.window
    assert s.char_start + s.win_start == h.char_start + w.start


def test_short_chunk_is_shown_whole():
    s = sources_from_hits([hit(1, "Short text here.")], "q", 110)[0]
    assert s.window == "Short text here." and s.win_start == 0


def test_block_header_and_citation_anchor_use_story_offsets():
    s = sources_from_hits([hit(3, LONG)], "What kind of snake was it?", 60)[0]
    m, _ = build_messages("q", [s], [], "")
    user = m[1]["content"]
    a, b = s.char_start + s.win_start, s.char_start + s.window_end
    assert f"chars={a}-{b}" in user and s.window in user
    assert FILLER * 12 not in user  # outside the window is not shown
    from detective_board.agent.answer import citations_for

    cites, _ = citations_for('Snake. [1: "the deadliest snake in India"]', [s])
    c = cites[0]
    assert LONG[c.anchor.char_start - s.char_start : c.anchor.char_end - s.char_start] == c.quote


def test_quote_outside_window_rejected_but_full_text_verbatim():
    s = sources_from_hits([hit(1, LONG)], "What kind of snake was it?", 40)[0]
    outside = "Mist hid the Surrey lane"
    assert outside in s.text and outside not in s.window
    r = self_check(f'Foggy. [1: "{outside}"]', [s])
    assert not r.ok and "shown excerpt" in r.problems[0]
    ok = self_check('A snake. [1: "the deadliest snake in India"]', [s])
    assert ok.ok


def test_budget_drops_lowest_ranked_source_and_renumbers():
    srcs = sources_from_hits([hit(i, "Word " * 300 + ".") for i in (1, 2, 3)], "q", 0)
    g = Source(4, "c", "s", 0, 3, "abc", "graph", "extracted", summary="person X")
    full = fit_prompt("q?", [*srcs, g], [], "", "", 10_000)
    assert full.dropped == [] and len(full.sources) == 4
    p = fit_prompt("q?", [*srcs, g], [], "", "", full.tokens - 5)
    assert p.dropped == [srcs[2].chunk_id]
    assert [s.n for s in p.sources] == [1, 2, 3] and p.sources[2].origin == "graph"
    assert p.tokens < full.tokens
    tiny = fit_prompt("q?", [*srcs, g], ["RULE RESULT R1 x"], "", "", 1)
    assert [s.origin for s in tiny.sources] == ["vector", "graph"]  # facts kept, 1 chunk stays
    assert "RULE RESULT R1 x" in tiny.messages[1]["content"]
    assert tiny.messages[1]["content"].rstrip().endswith("QUESTION: q?")


def test_agent_reports_windows_budget_and_tokens():
    hits = [hit(i, LONG) for i in (1, 2, 3)]
    cfg = AgentConfig(max_prompt_tokens=450, window_words=60, strategy="uniform")
    ev = list(make_agent(FakeLLM("x"), FakeRetriever(hits), config=cfg).ask("What snake?", ()))
    eq = next(e for e in ev if e.type == "enriched_query")
    assert eq.prompt_tokens_estimate == estimate_tokens(eq.prompt_chars) <= 450
    assert eq.dropped_chunks and eq.dropped_chunks[0] == hits[-1].chunk_id
    for st in eq.sources:
        assert st.window_start is not None and st.window_end > st.window_start
        assert st.window_char_start == st.char_start + st.window_start


def test_default_top_k_is_four():
    r = FakeRetriever([hit(i, "A snake. ") for i in range(1, 8)])
    list(make_agent(FakeLLM("x"), r).ask("What snake?", ()))
    assert r.calls[0][1] == 4 == AgentConfig().top_k


# ---- reasoning leak ---------------------------------------------------------
def test_strip_think_blocks():
    assert strip_reasoning("<think>hmm\nlong</think>\nAnswer. [1]") == "Answer. [1]"
    assert strip_reasoning("Answer.<think>never closed") == "Answer."


def test_preamble_detected():
    for t in ("Okay, let's see.", "Let me check the sources.", "First, I need to", "Hmm, so"):
        assert leaks_reasoning(t), t
    assert not leaks_reasoning('A swamp adder. [1: "swamp adder"]')


def test_reasoning_leak_fails_attempt_then_retry_succeeds():
    text = 'A snake. [1: "a deadly snake from India"]'
    llm = FakeLLM(["Okay, let's look at the sources. " + text, "<think>plan</think>" + text])
    ev = list(make_agent(llm).ask("What was the speckled band?", ()))
    checks = [e for e in ev if e.type == "citation_check"]
    assert checks[0].action == "retry" and "reasoning_leak" in checks[0].problems[0]
    assert "no reasoning" in llm.calls[1][1]["content"]
    assert ev[-1].status == "answered" and ev[-1].attempts == 2 and "<think>" not in ev[-1].answer


# ---- real data ----------------------------------------------------------------
def test_real_chunks_fit_budget_for_golden_questions():
    chunks = [json.loads(line) for line in (ROOT / "data/chunks.jsonl").read_text().splitlines()]
    by_id = {c["chunk_id"]: c for c in chunks}
    qs = [json.loads(x) for x in (ROOT / "eval/golden/questions.jsonl").read_text().splitlines()]
    qs = [q for q in qs if q["answerable"] and q["gold_quotes"]][:12]
    assert qs
    cfg = AgentConfig()
    for q in qs:
        gold = q["gold_quotes"][0]
        c = next(
            c for c in chunks if gold["quote"][:30] in c["text"] or c["story"] == gold["story"]
        )
        others = [x for x in chunks if x is not c and x["story"] == c["story"]][:2]
        from detective_board.retrieval import Hit

        hs = [
            Hit(x["chunk_id"], x["story"], x["char_start"], x["char_end"], 0.03, {}, {}, x["text"])
            for x in [c, *others]
        ][: cfg.top_k]
        srcs = sources_from_hits(hs, q["question"], cfg.window_words)
        p = fit_prompt(q["question"], srcs, [], "", "", cfg.max_prompt_tokens)
        assert p.tokens <= cfg.max_prompt_tokens, (q["id"], p.tokens)
        for s in p.sources:
            assert by_id[s.chunk_id]["text"][s.win_start : s.window_end] == s.window
            assert (
                len(s.window.split()) <= cfg.window_words * 1.2 or len(sentence_spans(s.text)) < 3
            )


# ---- IDF window selection -------------------------------------------------------
def _chunks():
    return [json.loads(x) for x in (ROOT / "data/chunks.jsonl").read_text().splitlines()]


def test_idf_is_deterministic_and_ranks_rare_words_higher():
    from detective_board.agent.window import idf_from_chunks

    ch = _chunks()
    texts, stories = [c["text"] for c in ch], [c["story"] for c in ch]
    a, b = idf_from_chunks(texts, stories), idf_from_chunks(texts, stories)
    assert a == b and a["adder"] > a["holm"] if "holm" in a else a["adder"] > 0
    assert a["roylott"] < a["adder"]  # a story-wide name weighs less than a rare noun


def test_g001_window_keeps_swamp_adder():
    from detective_board.agent.window import idf_from_jsonl

    ch = _chunks()
    c = next(x for x in ch if x["chunk_id"] == "speckled-band-0030")
    q = "What kind of snake killed Dr. Grimesby Roylott?"
    idf = idf_from_jsonl(str(ROOT / "data/chunks.jsonl"))
    w = best_window(c["text"], q, 110, idf)
    assert "swamp adder" in c["text"][w.start : w.end]
    assert len(c["text"][w.start : w.end].split()) <= 110 * 1.2


def test_agent_uses_idf_chunks(tmp_path):
    f = tmp_path / "chunks.jsonl"
    f.write_text(json.dumps({"text": LONG, "story": "s"}) + "\n")
    ag = make_agent(FakeLLM("x"), config=AgentConfig(idf_chunks=str(f)))
    assert ag.idf and ag.idf["adder"] > 0


def test_abbreviation_does_not_split_claim():
    from detective_board.agent.answer import split_claims

    claims = split_claims(
        'The snake that killed Dr. Grimesby Roylott was a swamp adder [1: "It is a swamp adder!"].'
    )
    assert len(claims) == 1
    assert claims[0].text.startswith("The snake that killed Dr. Grimesby")
    assert claims[0].cites


# ---- rank_full allocation -----------------------------------------------------
def test_defaults_and_strategy_validation():
    import pytest

    c = AgentConfig()
    assert (c.top_k, c.strategy, c.window_words, c.max_prompt_tokens) == (4, "rank_full", 60, 1200)
    with pytest.raises(ValueError, match="strategy"):
        AgentConfig(strategy="nope")


def test_rank_full_top1_whole_others_windows():
    hs = [hit(i, LONG) for i in (1, 2, 3)]
    r = sources_from_hits(hs, "What kind of snake?", 60, full_top1=True)
    assert r[0].window == LONG and r[0].win_start == 0 and r[0].window_end == len(LONG)
    for s in r[1:]:
        assert len(s.window) < len(LONG) and "swamp adder" in s.window
    u = sources_from_hits(hs, "What kind of snake?", 60)
    assert len(u[0].window) < len(LONG)  # uniform: all windows


def test_trace_reports_strategy_and_full_top1_is_citable():
    hs = [hit(i, LONG) for i in (1, 2, 3)]
    quote = "Mist hid the Surrey lane"  # far from the answer: only the full top-1 shows it
    llm = FakeLLM(f'Mist. [1: "{quote}"]')
    ev = list(make_agent(llm, FakeRetriever(hs)).ask("What kind of snake?", ()))
    eq = next(e for e in ev if e.type == "enriched_query")
    assert eq.strategy == "rank_full" and eq.window_words == 60
    assert (eq.sources[0].window_start, eq.sources[0].window_end) == (0, len(LONG))
    assert ev[-1].status == "answered"
    uni = list(
        make_agent(
            FakeLLM(f'Mist. [1: "{quote}"]'),
            FakeRetriever(hs),
            config=AgentConfig(strategy="uniform"),
        ).ask("What kind of snake?", ())
    )
    assert next(e for e in uni if e.type == "enriched_query").strategy == "uniform"
    assert uni[-1].status != "answered"  # quote outside the shown window


def test_real_chunks_rank_full_budget_never_cuts_top1():
    from detective_board.retrieval import Hit

    chunks = _chunks()
    qs = {
        q["id"]: q
        for q in map(json.loads, (ROOT / "eval/golden/questions.jsonl").read_text().splitlines())
    }
    cfg = AgentConfig()
    for qid in ("g001", "g007", "g028"):
        q = qs[qid]
        quote = q["gold_quotes"][0]["quote"][:25]
        gold = next(
            c for c in chunks if c["story"] == q["gold_quotes"][0]["story"] and quote in c["text"]
        )
        rest = [c for c in chunks if c["story"] == gold["story"] and c is not gold][: cfg.top_k - 1]
        hs = [
            Hit(c["chunk_id"], c["story"], c["char_start"], c["char_end"], 0.03, {}, {}, c["text"])
            for c in [gold, *rest]
        ]
        srcs = sources_from_hits(hs, q["question"], cfg.window_words, full_top1=True)
        assert srcs[0].window == gold["text"]
        p = fit_prompt(q["question"], srcs, [], "", "", cfg.max_prompt_tokens)
        assert p.tokens <= cfg.max_prompt_tokens, (qid, p.tokens)
        assert p.sources[0].window == gold["text"]
        tight = fit_prompt(q["question"], srcs, [], "", "", 1)  # everything droppable is dropped
        assert [s.chunk_id for s in tight.sources] == [gold["chunk_id"]]
        assert tight.dropped == [s.chunk_id for s in reversed(srcs[1:])]  # lowest rank first
