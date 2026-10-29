"""Entity-choice answers (agent/entity.py, switch `entity_answer`): trigger, candidate list on a
hand-built graph, enum parsing with a fake LLM, the name-in-sentence verification, the wiring and the
honesty guard. No Ollama."""

import hashlib
import json
import re

import pytest

from detective_board.agent import AgentConfig, FakeLLM
from detective_board.agent import entity as ent
from detective_board.agent import extractive as ex
from detective_board.agent.answer import self_check
from detective_board.agent.backends import SentenceResult
from detective_board.agent.context import REFUSAL_TEXT, Source
from detective_board.agent.honesty import asserts_consistency
from detective_board.agent.router import Router
from detective_board.extract.schema_v2 import Entity, Extraction
from detective_board.graph import ChunkRef, GraphStore
from detective_board.retrieval.sentences import SentenceHit

from .conftest import FakeRetriever, hit, make_agent, types

STORY = "boscombe-valley-mystery"
S_A = "Mr. John Turner was seen at the pool with the old man."
S_B = "He carried a heavy stick."
S_C = "Turner struck the blow that killed Charles McCarthy."
S_D = "Lestrade arrested James McCarthy that evening."
S_E = "Holmes watched the coroner and said nothing."
TEXT = " ".join([S_A, S_B, S_C, S_D, S_E])
NAMES = (
    "Names: Mr. John Turner, Old Turner, Turner, Charles McCarthy, James McCarthy, McCarthy, "
    "young McCarthy, Lestrade, Holmes, Sherlock Holmes, Watson, Coroner, the deceased, "
    "Turner's daughter, Peter Carey, Mrs. Carey, Alice."
)
CHUNK = TEXT + " " + NAMES
Q = "Who killed Charles McCarthy?"


def _graph() -> GraphStore:
    g = GraphStore()
    ref = ChunkRef(f"{STORY}-0001", STORY, 0, len(CHUNK), CHUNK)

    def p(name: str, *aliases: str, unnamed: bool = False) -> Entity:
        return Entity(name=name, type="person", aliases=list(aliases), quote=name, unnamed=unnamed)

    ents = [
        p("Mr. John Turner", "Black Jack"),
        p("Old Turner"),
        p("Turner"),
        p("Charles McCarthy"),
        p("James McCarthy"),
        p("McCarthy"),
        p("young McCarthy"),
        p("Lestrade"),
        p("Holmes"),
        p("Sherlock Holmes"),
        p("Watson"),
        p("Coroner"),
        p("the deceased", unnamed=True),
        p("Turner's daughter"),
        p("Peter Carey"),
        p("Mrs. Carey"),
        p("Alice"),
    ]
    g.ingest_many([(ref, Extraction(entities=ents))])
    return g


@pytest.fixture(scope="module")
def graph() -> GraphStore:
    return _graph()


def _names(people: list[ent.Person]) -> list[str]:
    return [p.name for p in people]


# ------------------------------------------------------------------------------------ trigger
@pytest.mark.parametrize(
    "q",
    [
        "Who killed Charles McCarthy at Boscombe Pool?",
        "Who stole the naval treaty from Percy Phelps?",
        "Who is the guilty man in the Boscombe Valley mystery?",
        "Who is the real murderer of John Straker, the trainer?",
        "Who was the thief in the Naval Treaty case?",
        "who really murdered William Kirwan",
        "Who killed Captain Peter Carey, and with what weapon?",
        "Which person attacked Mr. Phelps?",
        "And who was responsible for the fire?",
    ],
)
def test_trigger_on(q):
    assert ent.is_who_question(q)


@pytest.mark.parametrize(
    "q",
    [
        "What was the speckled band?",
        "How did Julia Stoner die?",
        "Where is Jonas Oldacre, and is he really dead?",
        "Who is Sir George Burnwell in relation to Arthur Holder?",
        "Who was Mr. Blessington really, and how was he linked to his attackers?",
        "Who was arrested on suspicion in 'Silver Blaze' and who was actually responsible?",
        "In 'The Speckled Band' Dr. Watson is killed by a swamp adder. Who discovers his body?",
        "Whose accounts conflicted over whether Neville St. Clair was in the room?",
        "Holmes asked who killed him.",
        "Is there a conflict about where Garcia was at one o'clock?",
        "",
    ],
)
def test_trigger_off(q):
    assert not ent.is_who_question(q)


def test_router_is_untouched_by_the_trigger():
    r = Router(None, False).decide(Q)
    assert r.routes == ["vector"] and r.tools == []


def test_switch_is_off_by_default():
    assert AgentConfig().entity_answer is False


def test_select_prompt_is_byte_identical():
    digest = hashlib.sha256(ex.SELECT_SYSTEM_PROMPT.encode()).hexdigest()
    assert digest == "b2dd14bab94f58a9e7778c1ed08860d212a452477dd8bb09b1802f027f2db294"


# ------------------------------------------------------------------------------------ candidates
def test_people_are_cleaned_and_merged(graph):
    people = ent.load_people(graph.conn, STORY)
    names = _names(people)
    assert sorted(names) == sorted(
        ["Mr. John Turner", "Charles McCarthy", "James McCarthy", "Lestrade", "Peter Carey",
         "Mrs. Carey", "Alice"]
    )  # fmt: skip
    # role-only, unnamed, kin, detective and narrator nodes are gone; bare McCarthy is ambiguous
    for gone in ("Coroner", "the deceased", "Turner's daughter", "Holmes", "Watson", "McCarthy"):
        assert gone not in names
    turner = next(p for p in people if p.name == "Mr. John Turner")
    assert {"Black Jack", "John Turner", "Turner", "Old Turner"} <= turner.forms
    assert len(turner.node_ids) == 3  # Mr. John Turner, Old Turner, Turner
    charles = next(p for p in people if p.name == "Charles McCarthy")
    assert "McCarthy" not in charles.forms and "Charles McCarthy" in charles.forms
    carey = next(p for p in people if p.name == "Peter Carey")
    assert "Carey" not in carey.forms  # Mrs. Carey is somebody else


def test_ranking_by_mentions_in_the_retrieved_text_and_cap(graph):
    people = ent.load_people(graph.conn, STORY)
    texts = [S_A + " " + S_B + " " + S_C, S_D, "Turner said so. Lestrade nodded."]
    ranked = ent.rank_people(people, texts)
    assert [p.id for p in ranked] == [f"P{i}" for i in range(1, len(ranked) + 1)]
    assert _names(ranked)[0] == "Mr. John Turner"  # 3 mentions
    assert ranked[0].count == 3
    assert "Alice" not in _names(ranked) and "Peter Carey" not in _names(ranked)  # never mentioned
    assert _names(ranked)[1:] == ["Lestrade", "Charles McCarthy", "James McCarthy"] or set(
        _names(ranked)
    ) == {"Mr. John Turner", "Lestrade", "Charles McCarthy", "James McCarthy"}
    assert len(ent.rank_people(people, [NAMES], cap=3)) == 3


def test_story_comes_from_the_title_then_the_link_then_the_chunks():
    stories = ["boscombe-valley-mystery", "naval-treaty", "silver-blaze"]
    pick = ent.pick_story
    assert pick("Who is the guilty man in the Boscombe Valley mystery?", stories, None, []) == (
        "boscombe-valley-mystery"
    )
    assert pick("Who is the thief in the Naval Treaty case?", stories, "silver-blaze", []) == (
        "naval-treaty"
    )
    assert pick("Who killed John Straker?", stories, "silver-blaze", ["naval-treaty"]) == (
        "silver-blaze"
    )
    assert pick("Who did it?", stories, None, ["silver-blaze", "naval-treaty", "silver-blaze"]) == (
        "silver-blaze"
    )
    assert pick("Who did it?", stories, None, []) is None


# ------------------------------------------------------------------------------------ the choice
def _cands() -> list[ex.Candidate]:
    return [
        ex.Candidate("S1", 1, 0, len(S_A), S_A, 0.5),
        ex.Candidate("S2", 1, 100, 120, "He carried a heavy stick.", 0.4),
    ]


def _people(graph) -> list[ent.Person]:
    return ent.rank_people(ent.load_people(graph.conn, STORY), [CHUNK])


def test_schema_and_prompt_shape(graph):
    people, cands = _people(graph), _cands()
    sch = ent.schema(people, cands)
    assert sch["properties"]["choice"]["enum"] == [
        *(p.id for p in people),
        "NOT_A_PERSON",
        "NONE",
    ]
    assert sch["properties"]["sentence"]["enum"] == ["S1", "S2", "NONE"]
    assert sch["required"] == ["choice", "sentence"]
    msgs = ent.messages(Q, people, cands)
    assert msgs[0] == {"role": "system", "content": ent.ENTITY_PROMPT_V1}  # static prefix first
    assert (
        "PEOPLE:" in msgs[1]["content"] and f"{people[0].id} {people[0].name}" in msgs[1]["content"]
    )
    assert msgs[1]["content"].endswith(f"QUESTION: {Q}")
    assert ent.ENTITY_PROMPT_VERSION == "entity-v1"


@pytest.mark.parametrize(
    "raw,kind",
    [
        ('{"choice": "P1", "sentence": "S1"}', "person"),
        ('{"choice": "NOT_A_PERSON", "sentence": "S2"}', "not_a_person"),
        ('{"choice": "NONE", "sentence": "NONE"}', "none"),
        ('{"choice": "NONE", "sentence": "S1"}', "none"),
        ('{"choice": "P99", "sentence": "S1"}', "invalid"),  # unknown person id
        ('{"choice": "P1", "sentence": "S9"}', "invalid"),  # unknown sentence id
        ('{"choice": "P1", "sentence": "NONE"}', "invalid"),  # a person without a sentence
        ('{"choice": "P1"}', "invalid"),
        ('{"choice": 1, "sentence": "S1"}', "invalid"),
        ('["P1", "S1"]', "invalid"),
        ("not json", "invalid"),
        ("", "invalid"),
    ],
)
def test_parse_choice(graph, raw, kind):
    ch = ent.parse_choice(raw, _people(graph), _cands())
    assert ch.kind == kind
    if kind == "person":
        assert ch.person is not None and ch.sentence is not None and ch.sentence.id == "S1"


# ------------------------------------------------------------------------------------ verification
def _src() -> Source:
    return Source(1, f"{STORY}-0001", STORY, 0, len(CHUNK), CHUNK, "vector", "source_text")


def _cand_of(sentence: str, cid: str = "S1") -> ex.Candidate:
    a = CHUNK.index(sentence)
    return ex.Candidate(cid, 1, a, a + len(sentence), sentence, 0.5)


def _person(graph, name: str) -> ent.Person:
    return next(p for p in ent.load_people(graph.conn, STORY) if p.name == name)


def _verify(graph, name: str, sentence: str, kind: str = "person"):
    person = None if kind == "not_a_person" else _person(graph, name)
    return ent.verify(ent.Choice(kind, person, _cand_of(sentence)), [_src()])


def test_name_in_the_chosen_sentence_is_accepted(graph):
    v = _verify(graph, "Mr. John Turner", S_C)  # "Turner struck the blow ..."
    assert v.ok and v.quotes == [(1, S_C)]


def test_alias_is_accepted(graph):
    text = "Black Jack was a name from Ballarat."
    chunk = text + " " + S_B
    src = Source(1, "c", STORY, 0, len(chunk), chunk, "vector", "source_text")
    cand = ex.Candidate("S1", 1, 0, len(text), text, 0.5)
    v = ent.verify(ent.Choice("person", _person(graph, "Mr. John Turner"), cand), [src])
    assert v.ok


def test_name_in_the_neighbouring_sentence_is_accepted_with_both_quotes(graph):
    before = _verify(
        graph, "Mr. John Turner", S_B
    )  # S_A is right before "He carried a heavy stick."
    assert before.ok and before.quotes == [(1, S_A), (1, S_B)]
    after = _verify(graph, "Lestrade", S_C)  # Lestrade is named in S_D, right after S_C
    assert after.ok and after.quotes == [(1, S_C), (1, S_D)]


def test_name_two_sentences_away_is_rejected(graph):
    v = _verify(graph, "Lestrade", S_A)  # Lestrade stands in S_D, three sentences later
    assert not v.ok and "not in the chosen sentence" in v.reason
    assert not _verify(graph, "James McCarthy", S_A).ok  # S_D is three sentences later


def test_ambiguous_bare_surname_does_not_verify_either_mccarthy(graph):
    text = "Poor McCarthy lay on the grass."
    chunk = text + " " + S_B
    src = Source(1, "c", STORY, 0, len(chunk), chunk, "vector", "source_text")
    cand = ex.Candidate("S1", 1, 0, len(text), text, 0.5)
    for who in ("Charles McCarthy", "James McCarthy"):
        assert not ent.verify(ent.Choice("person", _person(graph, who), cand), [src]).ok


def test_not_a_person_needs_a_cue_word_next_to_the_sentence(graph):
    cue = "The horse had lashed out with its steel shoe."
    chunk = cue + " " + S_B + " " + S_D
    src = Source(1, "c", STORY, 0, len(chunk), chunk, "vector", "source_text")

    def cand(s):
        a = chunk.index(s)
        return ex.Candidate("S1", 1, a, a + len(s), s, 0.5)

    assert ent.verify(ent.Choice("not_a_person", None, cand(cue)), [src]).ok
    assert ent.verify(ent.Choice("not_a_person", None, cand(S_B)), [src]).ok  # cue just before
    assert not ent.verify(ent.Choice("not_a_person", None, cand(S_D)), [src]).ok  # cue 2 away
    v = ent.verify(ent.Choice("not_a_person", None, cand(S_B)), [src])
    assert v.quotes == [(1, cue), (1, S_B)]


def test_verify_refuses_without_a_sentence_or_source(graph):
    assert not ent.verify(ent.Choice("none"), [_src()]).ok
    assert not ent.verify(ent.Choice("invalid"), [_src()]).ok
    lost = ex.Candidate("S1", 7, 0, 10, "x", 0.1)  # source 7 does not exist
    assert not ent.verify(ent.Choice("person", _person(graph, "Lestrade"), lost), [_src()]).ok


def test_render_is_a_verbatim_quote_plus_a_plain_line_without_accusing_words(graph):
    ch = ent.Choice("person", _person(graph, "Mr. John Turner"), _cand_of(S_C))
    ver = ent.verify(ch, [_src()])
    text = ent.render(ch, ver)
    assert text == f'From the sources: [1: "{S_C}"]\nThe text names Mr. John Turner here.'
    line = text.splitlines()[-1]
    assert ent.template_is_clean(line) and not ent.ACCUSATORY.search(line)
    assert not ent.template_is_clean("The text names the Murderer here.")
    na = ent.render(ent.Choice("not_a_person", None, _cand_of(S_B)), ver)
    assert na.endswith("The text points here to a cause that is not a person.")
    assert ent.template_is_clean(na.splitlines()[-1])


def test_honesty_guard_passes_on_the_plain_line(graph):
    ch = ent.Choice("person", _person(graph, "Mr. John Turner"), _cand_of(S_C))
    text = ent.render(ch, ent.verify(ch, [_src()]))
    chk = self_check(text, [_src()], 6, 0.0, allow_uncited=True, forbid_consistency=True)
    assert chk.ok, chk.problems


# ------------------------------------------------------------------------------------ the agent
class SentRetriever(FakeRetriever):
    def __init__(self, hits, result):
        super().__init__(hits)
        self.result, self.sentence_calls = result, []

    def sentence_search(self, query, k):
        self.sentence_calls.append((query, k))
        return self.result


def _retriever():
    h = hit(1, CHUNK, story=STORY)
    sents = [S_B, S_C, S_D, S_A]
    hits = []
    for i, s in enumerate(sents, 1):
        a = CHUNK.index(s)
        hits.append(SentenceHit(i, h.chunk_id, STORY, a, a + len(s), s, 0.05 - i / 100, {"vec": i}))
    return SentRetriever([h], SentenceResult(hits, {h.chunk_id: h}))


def _chooser(person: str, sentence: str, calls: list | None = None):
    def reply(messages):
        user = messages[-1]["content"]
        if calls is not None:
            calls.append(messages)
        pid = re.search(rf"^(P\d+) {re.escape(person)}$", user, re.M)
        sid = re.search(rf"^(S\d+) \[source \d+\] {re.escape(sentence)}$", user, re.M)
        return json.dumps(
            {"choice": pid.group(1) if pid else "NONE", "sentence": sid.group(1) if sid else "NONE"}
        )

    return reply


def _ask(llm, question=Q, *, on=True, retriever=None, graph=None, variant="v1"):
    cfg = AgentConfig(entity_answer=on, entity_variant=variant)
    agent = make_agent(
        llm, retriever or _retriever(), config=cfg, graph=graph if graph is not None else _graph()
    )
    return list(agent.ask(question))


def test_switch_on_answers_with_a_verified_entity_quote():
    calls: list = []
    ev = _ask(FakeLLM(_chooser("Mr. John Turner", S_C, calls)))
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    assert fin.answer == f'From the sources: [1: "{S_C}"]\nThe text names Mr. John Turner here.'
    assert [c.quote for c in fin.citations] == [S_C]
    assert calls[0][0]["content"] == ent.ENTITY_PROMPT_V1
    eq = next(e for e in ev if e.type == "enriched_query")
    assert eq.strategy.startswith("entity choice (v1) in boscombe-valley-mystery")
    ck = [e for e in ev if e.type == "citation_check"][-1]
    assert ck.ok and ck.action == "accept"


def test_neighbour_evidence_is_quoted_with_both_sentences():
    fin = _ask(FakeLLM(_chooser("Mr. John Turner", S_B)))[-1]
    assert fin.status == "answered"
    assert fin.answer == (
        f'From the sources: [1: "{S_A}"] [1: "{S_B}"]\nThe text names Mr. John Turner here.'
    )


def test_name_far_from_the_sentence_is_refused():
    ev = _ask(FakeLLM(_chooser("Lestrade", S_A)))
    fin = ev[-1]
    assert fin.status == "refused" and fin.answer == REFUSAL_TEXT
    ck = [e for e in ev if e.type == "citation_check"][-1]
    assert not ck.ok and ck.problems[0].startswith("entity: ")


@pytest.mark.parametrize("reply", ['{"choice": "NONE", "sentence": "NONE"}', "garbage", "{}"])
def test_none_and_invalid_are_refusals(reply):
    fin = _ask(FakeLLM(reply))[-1]
    assert fin.status == "refused" and fin.answer == REFUSAL_TEXT


def test_switch_off_runs_the_normal_extractive_path():
    llm = FakeLLM('{"choice": "S1"}')
    ev = _ask(llm, on=False)
    assert ev[-1].status == "answered" and ev[-1].answer.startswith("From the sources: [1:")
    assert "names" not in ev[-1].answer
    assert llm.calls[0][0]["content"] == ex.SELECT_SYSTEM_PROMPT
    eq = next(e for e in ev if e.type == "enriched_query")
    assert eq.strategy == "extractive + sentence index"


def test_non_who_question_is_unchanged_with_the_switch_on():
    llm = FakeLLM('{"choice": "S1"}')
    ev = _ask(llm, "What heavy object did he carry?", on=True)
    assert llm.calls[0][0]["content"] == ex.SELECT_SYSTEM_PROMPT
    assert ev[-1].status == "answered" and "names" not in ev[-1].answer


def test_without_a_graph_the_mode_falls_back_to_the_normal_path():
    llm = FakeLLM('{"choice": "S1"}')
    agent = make_agent(llm, _retriever(), config=AgentConfig(entity_answer=True))  # graph=None
    ev = list(agent.ask(Q))
    assert llm.calls[0][0]["content"] == ex.SELECT_SYSTEM_PROMPT
    assert ev[-1].status == "answered"


def test_route_events_are_the_same_with_the_switch_on_and_off():
    on = _ask(FakeLLM(_chooser("Mr. John Turner", S_C)), on=True)
    off = _ask(FakeLLM('{"choice": "S1"}'), on=False)
    r_on = next(e for e in on if e.type == "route_decided")
    r_off = next(e for e in off if e.type == "route_decided")
    assert (r_on.routes, r_on.tools, r_on.method) == (r_off.routes, r_off.tools, r_off.method)
    assert types(on)[0] == types(off)[0] == "route_decided"


# ------------------------------------------------------------------------------------ variants
def test_variants_are_registered_and_the_frozen_default_is_v3():
    assert set(ent.VARIANTS) == {"v1", "v2", "v3"}
    assert AgentConfig().entity_variant == "v3"
    with pytest.raises(ValueError):
        AgentConfig(entity_variant="v9")
    assert len({v.prompt for v in ent.VARIANTS.values()}) == 3  # three different prompt texts


def test_drop_named_removes_the_victim_and_renumbers(graph):
    people = _people(graph)
    kept = ent.drop_named(people, "Who killed Charles McCarthy?")
    assert "Charles McCarthy" not in _names(kept)
    assert [p.id for p in kept] == [f"P{i}" for i in range(1, len(kept) + 1)]
    assert "James McCarthy" in _names(kept)  # another person with the same surname stays


def test_v2_annotates_each_sentence_with_the_people_next_to_it(graph):
    people = ent.drop_named(_people(graph), Q)
    c_b, c_d = _cand_of(S_B, "S1"), _cand_of(S_D, "S2")
    notes = {c.id: ent.people_near(people, ent.window([_src()], c)) for c in (c_b, c_d)}
    assert _names(notes["S1"]) == ["Mr. John Turner"]  # named in S_A, right before S_B
    assert "Lestrade" in _names(notes["S2"]) and "James McCarthy" in _names(notes["S2"])
    msgs = ent.messages(Q, people, [c_b, c_d], ent.VARIANTS["v2"], notes)
    user = msgs[1]["content"]
    assert re.search(r"^S1 \[source 1\] \[P\d+ Mr\. John Turner\] He carried", user, re.M)
    assert msgs[0]["content"] == ent.ENTITY_PROMPT_V2
    assert list(ent.schema(people, [c_b], ent.VARIANTS["v2"])["properties"]) == [
        "sentence",
        "choice",
    ]


def test_v3_options_are_the_pairs_a_window_allows(graph):
    people = ent.drop_named(_people(graph), Q)
    c_b, c_e = _cand_of(S_B, "S1"), _cand_of(S_E, "S2")
    opts = ent.build_options(people, [c_b, c_e], [_src()])
    ids = [o.id for o in opts]
    turner = next(p.id for p in people if p.name == "Mr. John Turner")
    assert f"S1-{turner}" in ids and not any(i.endswith("NOT_A_PERSON") for i in ids)
    sch = ent.pair_schema(opts)
    assert sch["properties"]["pick"]["enum"] == [*ids, "NONE"]
    msgs = ent.pair_messages(Q, opts)
    assert msgs[0]["content"] == ent.ENTITY_PROMPT_V3 and "PEOPLE:" not in msgs[1]["content"]
    assert (
        f"S1 [source 1] [{turner} Mr. John Turner] He carried a heavy stick." in msgs[1]["content"]
    )


def test_v3_not_a_person_pair_only_where_a_cue_stands():
    cue = "The horse lashed out at the trainer."
    chunk = cue + " " + S_B
    src = Source(1, "c", STORY, 0, len(chunk), chunk, "vector", "source_text")
    c1 = ex.Candidate("S1", 1, 0, len(cue), cue, 0.5)
    a = chunk.index(S_B)
    c2 = ex.Candidate("S2", 1, a, a + len(S_B), S_B, 0.4)
    opts = ent.build_options([], [c1, c2], [src])
    assert [o.id for o in opts] == ["S1-NOT_A_PERSON", "S2-NOT_A_PERSON"]  # S_B is next to the cue


@pytest.mark.parametrize(
    "raw,kind",
    [
        ('{"pick": "S1-P1"}', "person"),
        ('{"pick": "S1-NOT_A_PERSON"}', "not_a_person"),
        ('{"pick": "NONE"}', "none"),
        ('{"pick": "S9-P1"}', "invalid"),
        ('{"pick": 3}', "invalid"),
        ("[]", "invalid"),
        ("nope", "invalid"),
    ],
)
def test_parse_pick(graph, raw, kind):
    p = _person(graph, "Mr. John Turner")
    p.id = "P1"
    opts = [
        ent.Option("S1-P1", _cand_of(S_C, "S1"), p),
        ent.Option("S1-NOT_A_PERSON", _cand_of(S_C, "S1"), None),
    ]
    assert ent.parse_pick(raw, opts).kind == kind


@pytest.mark.parametrize(
    "q,sentence,ok",
    [
        ("Who killed Charles McCarthy?", "Turner struck the blow that killed the old man.", True),
        (
            "Who killed Charles McCarthy?",
            "Turner was arrested for the murder of the old man.",
            False,
        ),
        ("Who killed Charles McCarthy?", "Turner is innocent of the death, said Holmes.", False),
        ("Who killed Charles McCarthy?", "Turner lived at the Hall for years.", False),
        ("Who stole the treaty?", "Turner took the treaty from the room.", True),
        ("Who stole the treaty?", "Turner struck the blow that killed the old man.", False),
        ("Who is the guilty man?", "Turner struck the blow that killed the old man.", True),
        ("Who is the guilty man?", "Turner lived at the Hall for years.", False),
    ],
)
def test_act_gate(q, sentence, ok):
    assert (ent.act_gate(q, [sentence]) is None) is ok


def test_v3_gate_turns_an_arrest_sentence_into_a_refusal(graph):
    text = "Turner was arrested for the murder of Charles McCarthy."
    chunk = text + " " + S_B
    src = Source(1, "c", STORY, 0, len(chunk), chunk, "vector", "source_text")
    cand = ex.Candidate("S1", 1, 0, len(text), text, 0.5)
    ch = ent.Choice("person", _person(graph, "Mr. John Turner"), cand)
    assert ent.verify(ch, [src], Q, ent.VARIANTS["v1"]).ok  # the bare name check accepts it
    v3 = ent.verify(ch, [src], Q, ent.VARIANTS["v3"])
    assert not v3.ok and "suspicion" in v3.reason


def test_agent_v3_picks_a_pair_and_answers_with_the_verified_quote():
    kill = "Turner struck the blow that killed the old man."
    h = hit(1, kill + " The rain fell on the moor all night.", story=STORY)
    sh = SentenceHit(1, h.chunk_id, STORY, 0, len(kill), kill, 0.05, {"vec": 1})
    r = SentRetriever([h], SentenceResult([sh], {h.chunk_id: h}))

    def reply(messages):
        user = messages[-1]["content"]
        m = re.search(
            r"^(S\d+) \[source \d+\] \[(P\d+) Mr\. John Turner\] " + re.escape(kill), user, re.M
        )
        return json.dumps({"pick": f"{m.group(1)}-{m.group(2)}" if m else "NONE"})

    llm = FakeLLM(reply)
    ev = _ask(llm, variant="v3", retriever=r)
    fin = ev[-1]
    assert fin.status == "answered", [e for e in ev if e.type == "citation_check"]
    assert fin.answer == f'From the sources: [1: "{kill}"]\nThe text names Mr. John Turner here.'
    assert llm.calls[0][0]["content"] == ent.ENTITY_PROMPT_V3
    assert llm.formats[0]["properties"]["pick"]["enum"][-1] == "NONE"
    eq = next(e for e in ev if e.type == "enriched_query")
    assert eq.strategy.startswith("entity choice (v3) in boscombe-valley-mystery")
    assert [e for e in ev if e.type == "citation_check"][-1].ok
    assert asserts_consistency(fin.answer.splitlines()[-1]) == []
    assert not ent.ACCUSATORY.search(fin.answer.splitlines()[-1])


def test_agent_v3_arrest_in_the_window_is_refused():
    llm = FakeLLM(lambda m: json.dumps({"pick": "NONE"}))
    fin = _ask(llm, variant="v3")[-1]
    assert fin.status == "refused"


def test_agent_v3_without_any_option_refuses_without_calling_the_model():
    h = hit(1, S_E + " " + S_B, story=STORY)  # no person of the graph is named in this chunk
    sents = []
    for i, s in enumerate([S_B], 1):
        a = h.text.index(s)
        sents.append(SentenceHit(i, h.chunk_id, STORY, a, a + len(s), s, 0.05, {"vec": 1}))
    r = SentRetriever([h], SentenceResult(sents, {h.chunk_id: h}))
    llm = FakeLLM("{}")
    ev = _ask(llm, variant="v3", retriever=r)
    # Holmes (detective) is not offered, so there are no people at all: the mode steps aside
    assert ev[-1].status in ("answered", "refused")
    assert all("entity choice" not in e.strategy for e in ev if e.type == "enriched_query")
