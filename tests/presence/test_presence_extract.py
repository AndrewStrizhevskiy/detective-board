"""Presence pass: schema, prompt, deterministic grounding and the runner (fake client only)."""

import json

from detective_board.extract import presence
from detective_board.extract.cache import ExtractCache
from detective_board.extract.llm import FakeClient
from detective_board.extract.pipeline import load_prompt
from detective_board.extract.presence import (
    PROMPT_V1,
    KnownEntities,
    PresenceConfig,
    PresenceExtractor,
    PresenceFact,
    ground_facts,
)

from .helpers import BV, WL, fact, fake_by_passage, rec, write_chunks

BV2 = f"{BV}-0002"
QUOTE_MC = (
    "On June 3rd, that is, on Monday last, McCarthy left his house at Hatherley about three in "
    "the afternoon and walked down to the Boscombe Pool"
)


def pf(**kw) -> PresenceFact:
    return PresenceFact.model_validate(fact(**kw))


def ground(chunk_id, facts, known=None, **kw):
    return ground_facts([pf(**f) for f in facts], rec(chunk_id)["text"], known, **kw)


def mc(**over):
    return {
        "person": "McCarthy", "place": "Hatherley", "time_text": "about three in the afternoon",
        "quote": QUOTE_MC, **over,
    }  # fmt: skip


# --- schema and prompt


def test_format_schema_is_inline_and_capped():
    s = presence.ollama_format_schema()
    assert "$ref" not in json.dumps(s) and "$defs" not in s
    assert s["properties"]["facts"]["maxItems"] == 6
    item = s["properties"]["facts"]["items"]
    assert set(item["required"]) == {"person", "place", "time_text", "quote"}
    assert set(item["properties"]) == {
        "person", "place", "time_text", "day_text", "polarity", "source", "speaker", "quote",
    }  # fmt: skip


def test_prompt_version_and_worked_example_is_self_consistent():
    p = load_prompt(PROMPT_V1)
    assert p.version == "presence-1" and "{{CHUNK}}" in p.template
    head = p.template.split("Example passage (invented):\n", 1)[1]
    passage, rest = head.split("\n\nExample output:\n", 1)
    out = json.loads(rest.split("\n(Nothing", 1)[0])
    facts = [PresenceFact.model_validate(f) for f in out["facts"]]
    assert [f.polarity for f in facts] == ["affirm", "affirm", "deny"]
    assert [f.source for f in facts] == ["narrator", "speech", "speech"]
    # the example is not from the corpus and passes the grounding rules it teaches
    corpus = (rec(f"{WL}-0006")["text"] + rec(BV2)["text"]).casefold()
    assert "greywater" not in corpus and "harlow" not in corpus
    res = ground_facts(facts, passage)
    assert len(res.facts) == 3 and res.dropped == []
    assert [f.source for f in res.facts] == ["narrator", "speech", "speech"]
    assert [f.speaker for f in res.facts] == [None, "Mr. Pell", "Pell"]


# --- grounding on real passages


def test_narrator_style_fact_on_real_text_is_kept_with_its_quote():
    out = ground(
        BV2, [mc(person="Charles McCarthy", day_text="On June 3rd, that is, on Monday last")]
    )
    (f,) = out.facts
    assert (f.person, f.place, f.time_text) == (
        "Charles McCarthy", "Hatherley", "about three in the afternoon",
    )  # fmt: skip
    assert f.day_text == "On June 3rd, that is, on Monday last"
    assert f.quote in rec(BV2)["text"] and f.context == []
    assert f.source == "speech" and f.speaker is None  # the whole chunk is inside quotation marks
    assert out.grounding["exact"] == 1


def test_fields_missing_from_the_quote_drop_the_fact():
    cases = {
        "PERSON_NOT_A_NAME": mc(person="he"),
        "PERSON_NOT_IN_QUOTE": mc(person="John Turner"),
        "PLACE_NOT_IN_QUOTE": mc(place="Ross"),
        "PLACE_DEICTIC": mc(place="his house"),
        "TIME_NOT_IN_QUOTE": mc(time_text="nine o'clock"),
        "TIME_NOT_TEMPORAL": mc(time_text="Hatherley"),
        "quote_not_grounded": mc(quote="McCarthy never left his house at Hatherley at all today"),
    }
    out = ground(BV2, list(cases.values()))
    assert out.facts == []
    assert [d["reason"] for d in out.dropped] == list(cases)


def test_day_text_not_in_quote_is_nulled_not_dropped():
    out = ground(BV2, [mc(day_text="that night")])
    (f,) = out.facts
    assert f.day_text is None and "DAY_NOT_IN_QUOTE" in f.codes


def test_surname_shared_by_two_known_people_does_not_identify_either():
    known = KnownEntities(
        people=[("Charles McCarthy", ["McCarthy"]), ("James McCarthy", ["Mr. James McCarthy"])]
    )
    out = ground(BV2, [mc(person="James McCarthy")], known)
    assert out.facts == [] and out.dropped[0]["reason"] == "PERSON_NOT_IN_QUOTE"
    assert ground(BV2, [mc(person="Charles McCarthy")], known).facts == []  # same: ambiguous
    # with only the father known, the surname identifies him and the graph's name is used
    alone = KnownEntities(people=[("Charles McCarthy", ["McCarthy"])])
    (f,) = ground(BV2, [mc(person="Mr. McCarthy")], alone).facts
    assert f.person == "Charles McCarthy"


def test_deictic_place_is_never_a_place():
    known = KnownEntities(people=[("Aloysius Garcia", ["Garcia", "Mr. Garcia"])])
    q = "Some time later Garcia looked in at my door"
    out = ground_facts(
        [pf(person="Mr. Garcia", place="my door", time_text="Some time later", quote=q)],
        rec(f"{WL}-0006")["text"],
        known,
    )
    assert out.facts == [] and out.dropped[0]["reason"] == "PLACE_DEICTIC"


def test_pronoun_statement_of_the_wisteria_case_is_not_extractable_strictly():
    """Gold c001: neither the Eccles nor the Baynes sentence names person, place and time. Strict
    grounding drops both; lenient keeps them as LOW context."""
    s1 = fact(
        person="Garcia", place="Wisteria Lodge", time_text="nearly one o’clock",
        quote="He apologised for having disturbed me so late, saying that it was nearly one o’clock.",
    )  # fmt: skip
    s2 = fact(
        person="Garcia", place="Oxshott Common", time_text="since one o’clock",
        quote="He had been there since one o’clock.",
    )  # fmt: skip
    strict = ground(f"{WL}-0010", [s2])
    assert strict.facts == [] and strict.dropped[0]["reason"] == "PERSON_NOT_IN_QUOTE"
    assert ground(f"{WL}-0006", [s1]).facts == []
    (f,) = ground(f"{WL}-0010", [s2], lenient=True).facts
    assert f.context == ["person", "place"] and f.source == "speech"
    assert f.speaker is None  # the model gave none


def test_polarity_needs_the_model_and_a_cue_in_the_quote():
    passage = (
        "Mr. Dacre told me he was never at the boathouse on Tuesday, said Pell. "
        "Captain Harlow reached Greywater Manor at about nine o'clock that night."
    )
    deny = fact(person="Mr. Dacre", place="the boathouse", time_text="Tuesday", polarity="deny",
                quote="Mr. Dacre told me he was never at the boathouse on Tuesday")  # fmt: skip
    wrong = {**deny, "polarity": "affirm"}
    no_cue = fact(person="Captain Harlow", place="Greywater Manor", polarity="deny",
                  time_text="about nine o'clock",
                  quote="Captain Harlow reached Greywater Manor at about nine o'clock that night.")  # fmt: skip
    out = ground_facts([pf(**x) for x in (deny, wrong, no_cue)], passage)
    assert [f.polarity for f in out.facts] == ["deny"]
    assert [d["reason"] for d in out.dropped] == ["POLARITY_UNCLEAR", "POLARITY_UNCLEAR"]


def test_at_most_six_facts_and_duplicates_collapse():
    words = QUOTE_MC.split()
    variants = [mc(quote=" ".join(words[: len(words) - k])) for k in range(8)]
    out = ground(BV2, [mc(), mc(), *variants])
    assert len(out.facts) == 6
    assert [d["reason"] for d in out.dropped][:1] == ["duplicate"]
    assert "over_limit" in {d["reason"] for d in out.dropped}


def test_grounding_is_deterministic():
    raw = [mc(day_text="Monday last"), mc(place="Ross")]
    a, b = ground(BV2, raw), ground(BV2, raw)
    assert a == b


# --- runner

SB4 = "silver-blaze-0004"
CM14 = "crooked-man-0014"
EDITH = "At a few minutes after nine the maid, Edith Baxter, carried down to the stables his supper"
CANNED = {
    "McCarthy left his house at Hatherley": [mc(day_text="Monday last")],
    EDITH[:40]: [
        fact(
            person="Edith Baxter",
            place="the stables",
            time_text="At a few minutes after nine",
            quote=EDITH,
        ),
        fact(
            person="Ned Hunter",
            place="the stables",
            time_text="nine o’clock",
            quote="the stables were locked up at nine o’clock",
        ),  # Ned is not in this quote
    ],  # fmt: skip
    "We were returning from the Watt Street Mission": [
        fact(
            person="We",
            place="the Watt Street Mission",
            time_text="about a quarter to nine o’clock",
            quote="We were returning from the Watt Street Mission about a quarter to nine o’clock.",
        ),
    ],  # fmt: skip
}


def chunks_file(tmp_path):
    return write_chunks(tmp_path / "chunks.jsonl", BV2, SB4, CM14, f"{WL}-0006")


def test_runner_resumes_from_cache_and_reports(tmp_path, capsys):
    cache, out = tmp_path / "c.sqlite", tmp_path / "out.jsonl"
    args = ["--model", "fake:8b", "--chunks", str(chunks_file(tmp_path)), "--cache", str(cache),
            "--out", str(out), "--prompt", str(PROMPT_V1)]  # fmt: skip
    client = fake_by_passage(CANNED)
    assert presence.main(args, client=client) == 0
    assert len(client.calls) == 4
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["chunks"] == 4 and report["facts_model"] == 4 and report["facts_kept"] == 2
    assert report["dropped_by_reason"] == {"PERSON_NOT_A_NAME": 1, "PERSON_NOT_IN_QUOTE": 1}
    assert report["fact_survival_rate"] == 0.5 and report["from_cache"] == 0
    recs = [json.loads(line) for line in out.read_text().splitlines()]
    assert [len(r["facts"]) for r in recs] == [1, 1, 0, 0]
    # second run: nothing reaches the model (resumable), same facts
    again = FakeClient(lambda p: 1 / 0)
    assert presence.main(args, client=again) == 0
    assert again.calls == []
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["from_cache"] == 4
    assert [json.loads(line)["facts"] for line in out.read_text().splitlines()] == [
        r["facts"] for r in recs
    ]


def test_runner_story_and_limit_filters(tmp_path):
    client = fake_by_passage(CANNED)
    args = ["--model", "fake:8b", "--chunks", str(chunks_file(tmp_path)),
            "--prompt", str(PROMPT_V1), "--cache", str(tmp_path / "c.sqlite"), "--story", BV, "--story", "silver-blaze"]  # fmt: skip
    assert presence.main(args, client=client) == 0
    assert len(client.calls) == 2
    client2 = fake_by_passage(CANNED)
    assert presence.main([*args, "--limit", "1"], client=client2) == 0
    assert client2.calls == []  # the first of the two is already cached


def test_cache_key_has_model_prompt_and_schema_version(tmp_path):
    prompt = load_prompt(PROMPT_V1)
    mk = lambda model, p=prompt: PresenceExtractor(  # noqa: E731
        FakeClient([]), PresenceConfig(model), ExtractCache(), p
    )
    base = mk("qwen3:8b").key("text")
    assert base != mk("qwen3:4b-instruct").key("text")
    assert base != mk("qwen3:8b", type(prompt)("presence-2", prompt.template)).key("text")
    assert base == mk("qwen3:8b").key("text")
    # a different pass or schema version would change the key: it is part of the hashed blob
    from detective_board.extract.cache import cache_key

    assert base == cache_key(
        "text", "qwen3:8b", "presence-1", "presence-1", PresenceConfig("x").options()
    )
    assert base != cache_key("text", "qwen3:8b", "presence-1", "2", PresenceConfig("x").options())


def test_model_error_and_bad_json_do_not_crash(tmp_path):
    ex = PresenceExtractor(FakeClient(["not json", '{"facts": "x"}', '{"facts": [1, {"person": 3}]}']),
                           PresenceConfig("m"), None)  # fmt: skip
    text = rec(BV2)["text"]
    assert ex.extract_chunk("a", "s", text).status == "failed"
    r = ex.extract_chunk("b", "s", text)
    assert r.dropped[0]["reason"] == "not_a_list"
    r = ex.extract_chunk("c", "s", text)
    assert [d["reason"] for d in r.dropped][0] == "not_an_object" and r.facts == []
    assert (
        PresenceExtractor(FakeClient(lambda p: 1 / 0), PresenceConfig("m"))
        .extract_chunk("d", "s", text)
        .status
        == "error"
    )
