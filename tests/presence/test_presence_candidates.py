"""presence-2: candidate lists in prompt and schema, list-resolved facts, cache key, ingest, e2e.

All with a fake client. Canned outputs prove the plumbing, not that a model produces them."""

import json

from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.extract import presence
from detective_board.extract.cache import ExtractCache
from detective_board.extract.llm import FakeClient
from detective_board.extract.pipeline import load_prompt
from detective_board.extract.presence import (
    DEFAULT_PROMPT,
    PresenceConfig,
    PresenceExtractor,
    PresenceFact,
    ground_facts,
)
from detective_board.extract.presence_candidates import (
    MAX_CANDIDATES,
    Candidates,
    CandidateSource,
    candidates_from_extraction,
    candidates_from_graph,
    candidates_from_text,
    rank,
)
from detective_board.extract.presence_schema import ollama_format_schema
from detective_board.extract.schema import Entity, Extraction
from detective_board.graph import ChunkRef, GraphStore

from .helpers import BV, WL, fact, fake_by_passage, rec, write_chunks

S1 = "He apologised for having disturbed me so late, saying that it was nearly one o’clock."
S2 = "He had been there since one o’clock."
TEXT = "Ann came in. He sat down at the inn at nine o'clock. Bob was not there."


def pf(**kw) -> PresenceFact:
    base = {"person": "Ann", "place": "the inn", "time_text": "nine o'clock", "quote": TEXT}
    return PresenceFact.model_validate(fact(**{**base, **kw}))


def cands(people=("Ann", "Bob"), places=("the inn",)) -> Candidates:
    return Candidates(tuple(people), tuple(places), {}, "graph")


def seed(db, entities: dict[str, list[Entity]]) -> GraphStore:
    g = GraphStore(str(db))
    for cid, ents in entities.items():
        g.ingest(ChunkRef.from_record(rec(cid)), Extraction(entities=ents))
    return g


# --- schema, prompt, caps


def test_schema_enum_is_built_from_the_lists_and_capped():
    s = ollama_format_schema(["Ann", "Bob"], ["the inn"])
    props = s["properties"]["facts"]["items"]["properties"]
    assert props["person"]["enum"] == ["Ann", "Bob", "UNKNOWN"]
    assert props["place"]["enum"] == ["the inn", "UNKNOWN"]
    assert props["time_text"]["type"] == "string" and "enum" not in props["time_text"]
    assert ollama_format_schema([], [])["properties"]["facts"]["items"]["properties"]["person"][
        "enum"
    ] == ["UNKNOWN"]
    plain = ollama_format_schema()["properties"]["facts"]["items"]["properties"]
    assert "enum" not in plain["person"] and "enum" not in plain["place"]  # presence-1 unchanged
    counts = {f'Name "{i}" \\ é’ {i}': i for i in range(100)} | {"UNKNOWN": 999}
    top = rank(counts)
    assert len(top) == MAX_CANDIDATES == 30 and top[0].endswith("99") and "UNKNOWN" not in top
    big = ollama_format_schema(top, top)
    json.dumps(big)  # a long list with quotes and backslashes still serialises
    assert len(big["properties"]["facts"]["items"]["properties"]["person"]["enum"]) == 31


def test_rank_orders_by_mentions_then_name_and_merges_case_variants():
    assert rank({"Bob": 2, "Ann": 2, "Zed": 5, "ann": 1}) == ("Zed", "Ann", "Bob")


def test_prompt_and_schema_sent_to_the_model_carry_the_lists(tmp_path):
    client = FakeClient(lambda p: '{"facts": []}')
    ex = PresenceExtractor(client, PresenceConfig("m"), ExtractCache(), load_prompt(DEFAULT_PROMPT))
    ex.extract_chunk("c1", "s", TEXT, None, Candidates(("Ann",), ("the inn",), {"Ann": ("Annie",)}))
    (req,) = client.calls
    assert "Known people in this passage: Ann (also: Annie)" in req.prompt
    assert "Known places in this passage: the inn" in req.prompt
    assert "{{" not in req.prompt and req.prompt.rstrip().endswith(TEXT)
    assert req.schema is not None
    assert req.schema["properties"]["facts"]["items"]["properties"]["person"]["enum"] == [
        "Ann",
        "UNKNOWN",
    ]


def test_prompt_v2_example_is_invented_and_self_consistent():
    p = load_prompt(DEFAULT_PROMPT)
    assert p.version == "presence-2"
    head = p.template.split("Example passage:\n", 1)[1]
    passage, rest = head.split("\n\nExample output:\n", 1)
    out = json.loads(rest.split("\n(", 1)[0])
    facts = [PresenceFact.model_validate(f) for f in out["facts"]]
    corpus = (rec(f"{WL}-0006")["text"] + rec(f"{BV}-0002")["text"]).casefold()
    assert "greywater" not in corpus and "harlow" not in corpus
    c = Candidates(
        ("Captain Harlow", "Miss Venn", "Mr. Pell", "Mr. Dacre"),
        ("Greywater Manor", "the conservatory", "the boathouse"),
    )
    res = ground_facts(facts, passage, candidates=c)
    assert [f.person for f in res.facts] == ["Captain Harlow"] * 2 + ["Miss Venn", "Mr. Dacre"]
    assert [f.person_resolution for f in res.facts] == ["quote", "context", "quote", "context"]
    assert [d["reason"] for d in res.dropped] == ["PERSON_UNKNOWN"]  # the UNKNOWN case
    assert res.facts[-1].polarity == "deny" and res.facts[-1].source == "speech"


# --- grounding through the list


def test_pronoun_is_resolved_through_the_list_and_marked_context():
    out = ground_facts(
        [
            pf(
                person="Bob",
                place="the inn",
                time_text="nine o'clock",
                quote="He sat down at the inn at nine o'clock.",
            )
        ],
        TEXT,
        candidates=cands(),
    )
    (f,) = out.facts
    assert f.person == "Bob" and f.person_resolution == "context" and f.place_resolution == "quote"
    assert f.context == ["person"] and out.dropped == []


def test_unknown_and_non_candidates_are_dropped_with_codes():
    q = "He sat down at the inn at nine o'clock."
    out = ground_facts(
        [
            pf(person="UNKNOWN", quote=q),
            pf(person="Carol", quote=q),
            pf(person="he", quote=q),
            pf(person="Ann", place="UNKNOWN", quote=q),
            pf(person="Ann", place="the cellar", quote=q),
        ],
        TEXT,
        candidates=cands(),
    )
    assert out.facts == []
    assert [d["reason"] for d in out.dropped] == [
        "PERSON_UNKNOWN",
        "PERSON_NOT_IN_CANDIDATES",
        "PERSON_NOT_IN_CANDIDATES",
        "PLACE_UNKNOWN",
        "PLACE_NOT_IN_CANDIDATES",
    ]


def test_literal_mode_keeps_the_quote_requirement():
    q = "He sat down at the inn at nine o'clock."
    p = pf(person="Bob", quote=q)
    assert ground_facts([p], TEXT, candidates=cands(), literal=True).dropped[0]["reason"] == (
        "PERSON_NOT_IN_QUOTE"
    )
    p = pf(
        person="Ann", place="the inn", quote="Ann came in. He sat down at the inn at nine o'clock."
    )
    assert len(ground_facts([p], TEXT, candidates=cands(), literal=True).facts) == 1
    q2 = "Bob was not there."
    d = ground_facts(
        [pf(person="Bob", place="the inn", quote=q2, time_text="nine o'clock", polarity="deny")],
        TEXT,
        candidates=cands(),
        literal=True,
    )
    assert d.dropped[0]["reason"] in ("PLACE_NOT_IN_QUOTE", "TIME_NOT_IN_QUOTE")


# --- cache key


def test_cache_key_has_prompt_schema_and_candidate_hash():
    ex = PresenceExtractor(FakeClient([]), PresenceConfig("m"), None, load_prompt(DEFAULT_PROMPT))
    a, b = cands(), cands(people=("Ann", "Bob", "Carol"))
    assert ex.key(TEXT, a) == ex.key(TEXT, cands())
    assert ex.key(TEXT, a) != ex.key(TEXT, b)
    assert ex.key(TEXT, a) != ex.key(TEXT, cands(places=("the inn", "the pier")))
    assert ex.schema_version == "presence-2" and ex.prompt.version == "presence-2"
    v1 = PresenceExtractor(
        FakeClient([]), PresenceConfig("m"), None, load_prompt(presence.PROMPT_V1)
    )
    assert v1.key(TEXT) != ex.key(TEXT, a)


def test_changed_list_calls_the_model_again_but_same_list_hits_the_cache():
    client = FakeClient(lambda p: '{"facts": []}')
    cache = ExtractCache()
    ex = PresenceExtractor(client, PresenceConfig("m"), cache, load_prompt(DEFAULT_PROMPT))
    ex.extract_chunk("c", "s", TEXT, None, cands())
    ex.extract_chunk("c", "s", TEXT, None, cands())
    assert len(client.calls) == 1
    ex.extract_chunk("c", "s", TEXT, None, cands(people=("Ann", "Bob", "Dan")))
    assert len(client.calls) == 2


# --- candidate sources


def test_graph_candidates_count_mentions_and_ignore_presence_mentions(tmp_path):
    cid = f"{WL}-0006"
    t = rec(cid)["text"]
    g = seed(
        tmp_path / "g.sqlite",
        {cid: [Entity(name="Garcia", type="person", quote="Garcia"),
               Entity(name="Wisteria Lodge", type="place", quote="Wisteria Lodge"),
               Entity(name="the deceased", type="person", quote="Garcia")]},
    )  # fmt: skip
    c = candidates_from_graph(g, cid)
    assert c is not None and c.people == ("Garcia",) and c.places == ("Wisteria Lodge",)
    assert c.source == "graph" and candidates_from_graph(g, "nope-0001") is None
    # the presence pass adds an implicit person; the next run must see the same lists
    gf = ground_facts(
        [PresenceFact.model_validate(fact(person="Garcia", place="Wisteria Lodge", time_text="nearly one o’clock", quote=S1))],
        t, candidates=c,
    )  # fmt: skip
    g.ingest_presence(ChunkRef.from_record(rec(cid)), gf.facts)
    assert candidates_from_graph(g, cid) == c


def test_extraction_cache_and_text_detector_and_fallbacks():
    raw = json.dumps({"entities": [
        {"name": "Ann", "type": "person", "aliases": ["Annie"], "quote": "Ann"},
        {"name": "the inn", "type": "place", "quote": "the inn"},
        {"name": "ring", "type": "item", "quote": "ring"},
    ]})  # fmt: skip
    c = candidates_from_extraction(raw, TEXT)
    assert c is not None and c.people == ("Ann",) and c.places == ("the inn",)
    assert c.aliases == {"Ann": ("Annie",)} and c.source == "cache"
    assert candidates_from_extraction("not json", TEXT) is None
    t = candidates_from_text(
        'Captain Harlow reached Greywater Manor. "I saw Miss Venn," said Pell.'
    )
    assert t is not None and t.places == ("Greywater Manor",)
    assert set(t.people) == {"Captain Harlow", "Miss Venn", "Pell"} and t.source == "text"
    # fallbacks: graph empty -> cache -> text; mode text ignores both
    store = GraphStore()
    lookup = lambda text: {"text": raw}  # noqa: E731
    assert CandidateSource("graph", store, lookup).for_chunk("x", TEXT).source == "cache"
    assert CandidateSource("graph", store, None).for_chunk("x", TEXT).source == "text"
    assert CandidateSource("text", store, lookup).for_chunk("x", TEXT).source == "text"
    assert CandidateSource("cache", None, lookup).for_chunk("x", TEXT).source == "cache"


# --- ingest marks context-resolved facts LOW


def test_ingest_marks_list_resolved_facts_low():
    g = GraphStore()
    chunk = ChunkRef(chunk_id="syn-0001", story="syn", char_start=0, char_end=len(TEXT), text=TEXT)
    g.ingest(chunk, Extraction(entities=[Entity(name="Bob", type="person", quote="Bob")]))
    q = "He sat down at the inn at nine o'clock."
    f = ground_facts([pf(person="Bob", quote=q)], TEXT, candidates=cands()).facts
    assert g.ingest_presence(chunk, f).events == 1
    ev = g.conn.execute(
        "SELECT confidence, conf_reason, props_json FROM g_node WHERE kind='event'"
    ).fetchone()
    props = json.loads(ev["props_json"])
    assert (ev["confidence"], ev["conf_reason"]) == ("low", "inherited_context")
    assert props["person_resolution"] == "context" and "place_resolution" not in props
    g2 = GraphStore()  # the same fact resolved literally is not LOW
    g2.ingest(chunk, Extraction(entities=[Entity(name="Ann", type="person", quote="Ann")]))
    q2 = "Ann came in. He sat down at the inn at nine o'clock."
    f2 = ground_facts([pf(person="Ann", quote=q2)], TEXT, candidates=cands()).facts
    g2.ingest_presence(chunk, f2)
    props2 = g2.conn.execute("SELECT props_json FROM g_node WHERE kind='event'").fetchone()[0]
    assert "person_resolution" not in json.loads(props2)


# --- end to end


def test_wisteria_c001_candidates_resolve_garcia_to_a_conditional_r1_finding(tmp_path):
    ids = (f"{WL}-0006", f"{WL}-0010")
    chunks = write_chunks(tmp_path / "chunks.jsonl", *ids)
    db = tmp_path / "g.sqlite"
    # what a generic extraction could have found (canned): the dead man of 0010 is Garcia
    seed(db, {
        ids[0]: [Entity(name="Garcia", type="person", quote="Garcia"),
                 Entity(name="Wisteria Lodge", type="place", quote="Wisteria Lodge")],
        ids[1]: [Entity(name="Garcia", type="person", quote=S2),
                 Entity(name="Oxshott Common", type="place", quote=S2)],
    }).close()  # fmt: skip
    client = fake_by_passage({
        "Some time later Garcia looked in": [
            fact(person="Garcia", place="Wisteria Lodge", time_text="nearly one o’clock",
                 day_text="that night", source="speech", speaker="Scott Eccles", quote=S1)],
        "He had been there since one o’clock": [
            fact(person="Garcia", place="Oxshott Common", time_text="since one o’clock",
                 day_text="that night", source="speech", speaker="Inspector Baynes", quote=S2)],
    })  # fmt: skip
    args = ["--model", "fake", "--chunks", str(chunks), "--cache", str(tmp_path / "c.sqlite"),
            "--graph-db", str(db)]  # fmt: skip
    # day_text "that night" is in neither quote: the day comes from --lenient (LOW context)
    assert presence.main([*args, "--lenient"], client=client) == 0
    assert "Known people in this passage: Garcia" in client.calls[0].prompt
    g = GraphStore(str(db))
    res = InProcessRulesClient(g).call("find_contradictions", {"story": WL}, timeout=1)
    assert res["status"] == "ok" and [f["rule"] for f in res["findings"]] == ["R1"]
    (f,) = res["findings"]
    assert f["provenance"] == "conditional" and f["reason_code"] == "OVERLAP_DIFFERENT_PLACES"
    assert sorted(a["quote"] for a in f["explanation"]["anchors"]) == sorted([S1, S2])
    # --literal keeps the old strict meaning: nothing survives, so no finding
    lit = tmp_path / "lit.sqlite"
    seed(lit, {ids[0]: [Entity(name="Garcia", type="person", quote="Garcia")]}).close()
    assert (
        presence.main(
            [*args[:-1], str(lit), "--literal", "--cache", str(tmp_path / "c2")], client=client
        )
        == 0
    )
    gl = GraphStore(str(lit))
    assert (
        InProcessRulesClient(gl).call("find_contradictions", {"story": WL}, timeout=1)["findings"]
        == []
    )


def test_boscombe_c042_with_candidates_is_still_not_flagged(tmp_path):
    ids = [f"{BV}-0002", f"{BV}-0003", f"{BV}-0007"]
    chunks = write_chunks(tmp_path / "chunks.jsonl", *ids)
    db = tmp_path / "g.sqlite"
    P = lambda n, q: Entity(name=n, type="person", quote=q)  # noqa: E731
    L = lambda n, q: Entity(name=n, type="place", quote=q)  # noqa: E731
    seed(db, {
        ids[0]: [P("Charles McCarthy", "Charles McCarthy"), L("Hatherley", "Hatherley"),
                 L("Boscombe Pool", "Boscombe Pool")],
        ids[1]: [P("James McCarthy", "James McCarthy"), L("Boscombe Pool", "Boscombe Pool")],
        ids[2]: [P("Crowder", "Crowder"), L("Boscombe Pool", "Boscombe Pool")],
    }).close()  # fmt: skip
    from .test_presence_graph import QUOTE_JAMES, QUOTE_MC

    at3, day = "about three in the afternoon", "On June 3rd, that is, on Monday last"
    client = fake_by_passage({
        "McCarthy left his house at Hatherley": [
            fact(person="Charles McCarthy", place="Hatherley", time_text=at3, day_text=day, quote=QUOTE_MC),
            fact(person="Charles McCarthy", place="Boscombe Pool", time_text=at3, day_text=day, quote=QUOTE_MC)],
        "I had been away from home for three days": [
            fact(person="James McCarthy", place="Boscombe Pool", source="speech",
                 time_text="the morning of last Monday, the 3rd", day_text="last Monday, the 3rd",
                 speaker="James McCarthy", quote=QUOTE_JAMES)],
    })  # fmt: skip
    rc = presence.main(["--model", "fake", "--chunks", str(chunks), "--cache", str(tmp_path / "c"),
                        "--graph-db", str(db)], client=client)  # fmt: skip
    assert rc == 0
    g = GraphStore(str(db))
    assert g.stats()["event"] >= 2
    res = InProcessRulesClient(g).call("find_contradictions", {"story": BV}, timeout=1)
    assert res == {"status": "ok", "findings": [], "truncated": False}
