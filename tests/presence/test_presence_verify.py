"""Verification and self-consistency voting of the presence pass (fake clients only: this proves
the plumbing and the decision rules, not that any model verifies well)."""

import json

import pytest

from detective_board.extract import presence
from detective_board.extract.cache import ExtractCache
from detective_board.extract.llm import FakeClient
from detective_board.extract.pipeline import load_prompt
from detective_board.extract.presence import PROMPT_V1, PresenceConfig, PresenceExtractor
from detective_board.extract.presence_schema import GroundedFact
from detective_board.extract.presence_verify import (
    PresenceVerifier,
    VerifyAnswer,
    VerifyConfig,
    context_sentences,
    decide,
    load_verify_prompt,
    needed_votes,
    parse_answer,
    verify_schema,
    vote,
)
from detective_board.graph import ChunkRef, GraphStore

from .helpers import fact

TEXT = (
    "Lady Corbin retired early. Mr. Fenwick sat in the library until about eleven o'clock. "
    "Then he locked the door. Captain Harlow was at Ashby Grange at noon. The rain stopped."
)
Q1 = "Mr. Fenwick sat in the library until about eleven o'clock."
Q2 = "Captain Harlow was at Ashby Grange at noon."


def good(**kw) -> dict:
    return fact(person="Mr. Fenwick", place="the library", time_text="about eleven o'clock",
                quote=Q1, **kw)  # fmt: skip


def wrong(**kw) -> dict:
    # right quote, wrong person: Harlow is not in Q1... use Q2 with Fenwick named in it? no: the
    # person must be in the quote to ground, so the error is a swapped place/time pairing instead
    return fact(person="Captain Harlow", place="Ashby Grange", time_text="at noon", quote=Q2, **kw)


ANSWERS = {
    "yes": {"person_ok": "yes", "place_ok": "yes", "time_ok": "yes", "verdict": "yes"},
    "no": {"person_ok": "yes", "place_ok": "no", "time_ok": "yes", "verdict": "no"},
    "wrong_person": {"person_ok": "no", "place_ok": "yes", "time_ok": "yes", "verdict": "no"},
    "partly_time": {"person_ok": "yes", "place_ok": "yes", "time_ok": "no", "verdict": "partly"},
    "partly_person": {"person_ok": "no", "place_ok": "yes", "time_ok": "yes", "verdict": "partly"},
}


def make_client(extract_facts_by_call, verdicts):
    """Extraction answers come from the list in order (cycling); a verification prompt (has
    'Claim:' after the examples) gets the canned answer chosen by the person in the claim."""
    n = {"i": 0}

    def answer(prompt: str) -> str:
        if "Now the real case." in prompt:
            claim = prompt.rsplit("Claim: ", 1)[1]
            for who, key in verdicts.items():
                if claim.startswith(who):
                    return json.dumps(ANSWERS[key])
            raise AssertionError(claim)
        facts = extract_facts_by_call[n["i"] % len(extract_facts_by_call)]
        n["i"] += 1
        return json.dumps({"facts": facts})

    return FakeClient(answer)


def extractor(client, cache=None, *, samples=1, verify=True, partly=False, model="m"):
    cache = cache if cache is not None else ExtractCache()
    ver = (
        PresenceVerifier(client, VerifyConfig(model, accept_partly=partly), cache)
        if verify
        else None
    )
    return PresenceExtractor(
        client, PresenceConfig(model, samples=samples), cache, load_prompt(PROMPT_V1), ver
    )


def run(ex):
    return ex.extract_chunk("s-0001", "s", TEXT)


# --- prompt, schema, parsing


def test_prompt_is_versioned_has_invented_example_and_renders_all_slots():
    p = load_verify_prompt()
    assert p.version.startswith("presence-verify-")
    assert "(invented)" in p.template and "Fenwick" in p.template
    out = p.render(previous="PRV", quote="QQQ", next="NXT", claim="CLM")
    assert "{{" not in out and all(x in out for x in ("PRV", "QQQ", "NXT", "CLM"))


def test_schema_is_closed_enum_only():
    s = verify_schema()
    assert s["additionalProperties"] is False
    assert s["properties"]["verdict"]["enum"] == ["yes", "partly", "no"]
    assert s["properties"]["person_ok"]["enum"] == ["yes", "no"]
    assert set(s["required"]) == {"verdict", "person_ok", "place_ok", "time_ok"}


def test_parse_answer_rejects_anything_off_schema():
    assert parse_answer(json.dumps(ANSWERS["yes"]))[0] == ANSWERS["yes"]
    for bad in ("nope", "[]", '{"verdict": "maybe"}', json.dumps({**ANSWERS["yes"], "time_ok": 1})):
        assert parse_answer(bad)[0] is None


def test_context_sentences_previous_and_next_and_abbreviation():
    assert context_sentences(TEXT, Q1) == ("Lady Corbin retired early.", "Then he locked the door.")
    assert context_sentences(TEXT, "Lady Corbin retired early.")[0] == ""
    assert context_sentences(TEXT, "not in the text") == ("", "")


# --- decision rules


@pytest.mark.parametrize(
    ("ans", "partly", "accepted", "detail", "nulled"),
    [
        ("yes", False, True, "yes", []),
        ("no", True, False, "no", []),
        ("wrong_person", True, False, "person_no", []),
        ("partly_time", False, False, "partly", []),
        ("partly_time", True, True, "partly_accepted", ["time_text"]),
        ("partly_person", True, False, "person_no", []),  # a person is never nulled
    ],
)
def test_decide(ans, partly, accepted, detail, nulled):
    a = VerifyAnswer("ok", **ANSWERS[ans])
    d = decide(a, partly)
    assert (d.accepted, d.detail, d.nulled) == (accepted, detail, nulled)


def test_decide_inconsistent_yes_and_failures():
    yes_but_place_no = VerifyAnswer("ok", "yes", "yes", "no", "yes")
    assert decide(yes_but_place_no, False).detail == "partly"
    assert decide(yes_but_place_no, True).nulled == ["place"]
    partly_no_field = VerifyAnswer("ok", "partly", "yes", "yes", "yes")
    assert decide(partly_no_field, True).detail == "partly_no_field"
    assert not decide(VerifyAnswer("unparseable"), True).accepted
    assert not decide(VerifyAnswer("error"), True).accepted


# --- the verifier in the extractor


def test_wrong_fact_rejected_right_one_kept_and_recorded():
    client = make_client(
        [[good(), wrong()]], {"Mr. Fenwick": "yes", "Captain Harlow": "wrong_person"}
    )
    res = run(extractor(client))
    assert [f["person"] for f in res.facts] == ["Mr. Fenwick"]
    f = res.facts[0]
    assert f["verify"]["verdict"] == "yes" and f["verify"]["prompt_version"].startswith("presence-")
    assert f["verify"]["model"] == "m" and f["context"] == []
    (d,) = [d for d in res.dropped if d["reason"] == "VERIFY_REJECTED"]
    assert (
        d["quote"] == Q2
        and d["verify"]["person_ok"] == "no"
        and d["verify"]["detail"] == "person_no"
    )
    assert [len(res.stages[k]) for k in ("grounded", "voted", "verified")] == [2, 2, 1]
    assert res.verification["calls"] == 2 and res.verification["rejected"] == 1


def test_verifier_sees_quote_neighbours_and_claim():
    client = make_client([[good()]], {"Mr. Fenwick": "yes"})
    run(extractor(client))
    vp = [c.prompt for c in client.calls if "Now the real case." in c.prompt][0]
    tail = vp.rsplit("Now the real case.", 1)[1]
    assert "Previous: Lady Corbin retired early." in tail and f"Quote: {Q1}" in tail
    assert "Next: Then he locked the door." in tail
    assert "Claim: Mr. Fenwick was at the library at about eleven o'clock" in tail
    vreq = [c for c in client.calls if "Now the real case." in c.prompt][0]
    assert vreq.schema == verify_schema() and vreq.options["temperature"] == 0.0


def test_no_verifier_means_no_extra_calls_and_no_verify_field():
    client = make_client([[good()]], {})
    res = run(extractor(client, verify=False))
    assert len(client.calls) == 1 and res.facts[0]["verify"] is None
    assert res.verification == {}


def test_partly_default_reject_and_accept_with_failing_field_nulled_low():
    verdicts = {"Mr. Fenwick": "partly_time"}
    res = run(extractor(make_client([[good()]], verdicts)))
    assert res.facts == [] and res.dropped[-1]["verify"]["detail"] == "partly"
    res = run(extractor(make_client([[good()]], verdicts), partly=True))
    (f,) = res.facts
    assert f["context"] == ["time_text"] and "VERIFY_PARTLY" in f["codes"]
    assert f["verify"]["detail"] == "partly_accepted" and f["verify"]["nulled"] == ["time_text"]
    g = GraphStore(":memory:")
    c = ChunkRef(chunk_id="s-0001", story="s", char_start=0, char_end=len(TEXT), text=TEXT)
    g.ingest_presence(c, res.grounded_facts())
    ev = g.conn.execute("SELECT props_json, confidence, conf_reason FROM g_node WHERE kind='event'")
    props, conf, why = tuple(ev.fetchone())
    p = json.loads(props)
    assert (conf, why) == ("low", "inherited_context")
    assert (
        p["time_text"] is None
        and p["time_norm"]["exact"] is False
        and p["verify"] == "partly_accepted"
    )


def test_verified_context_resolved_fact_stays_low_and_yes_does_not_raise_confidence():
    f = GroundedFact(
        person="Mr. Fenwick", place="the library", time_text="about eleven o'clock", quote=Q1,
        person_resolution="context", context=["person"],
        verify={"verdict": "yes", "detail": "yes"},
    )  # fmt: skip
    g = GraphStore(":memory:")
    c = ChunkRef(chunk_id="s-0001", story="s", char_start=0, char_end=len(TEXT), text=TEXT)
    g.ingest_presence(c, [f])
    ev = g.conn.execute("SELECT confidence, conf_reason FROM g_node WHERE kind='event'").fetchone()
    assert tuple(ev) == ("low", "inherited_context")


def test_verifier_error_and_garbage_reject_and_are_not_cached():
    cache = ExtractCache()
    calls = {"n": 0}

    def answer(prompt):
        if "Now the real case." in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return "garbage"
        return json.dumps({"facts": [good()]})

    ex = extractor(FakeClient(answer), cache)
    r1 = run(ex)
    assert r1.facts == [] and r1.dropped[-1]["verify"]["detail"] == "error"
    r2 = run(ex)  # the error was not cached: asked again, now garbage (which is cached)
    assert r2.dropped[-1]["verify"]["detail"] == "unparseable"
    before = calls["n"]
    run(ex)
    assert calls["n"] == before


# --- cache keys


def test_verifier_cache_key_prefix_model_prompt_and_content():
    cache = ExtractCache()
    f = GroundedFact(person="Mr. Fenwick", place="the library", time_text="eleven", quote=Q1)
    mk = lambda **kw: PresenceVerifier(  # noqa: E731
        FakeClient([]), VerifyConfig(kw.pop("model", "m")), cache, kw.pop("prompt", None)
    )
    base = mk().key(TEXT, f)
    assert base.startswith("verify:") and base == mk().key(TEXT, f)
    assert base != mk(model="other").key(TEXT, f)
    p = load_verify_prompt()
    assert base != mk(prompt=type(p)("presence-verify-9", p.template)).key(TEXT, f)
    assert base != mk().key(TEXT, f.model_copy(update={"place": "the hall"}))
    assert base != mk().key(TEXT.replace("Then he", "Then she"), f)
    ex = extractor(FakeClient([]), cache)
    assert not ex.key(TEXT).startswith("verify:")


def test_sample_keys_differ_and_single_sample_key_is_unchanged():
    one = extractor(FakeClient([]), verify=False)
    three = extractor(FakeClient([]), samples=3, verify=False)
    assert one.key(TEXT) == one.key(TEXT, sample=0)
    keys = {three.key(TEXT, sample=k) for k in range(3)}
    assert len(keys) == 3 and one.key(TEXT) not in keys
    assert three.cfg.sample_options(2)["seed"] == 44 and three.cfg.sample_options(1)[
        "temperature"
    ] == pytest.approx(0.3)
    assert one.cfg.sample_options(0) == one.cfg.options()


# --- voting


@pytest.mark.parametrize(("n", "need"), [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3)])
def test_needed_votes(n, need):
    assert needed_votes(n) == need


def gfact(**kw) -> GroundedFact:
    base = dict(
        person="Mr. Fenwick", place="the library", time_text="about eleven o'clock", quote=Q1
    )
    return GroundedFact(**{**base, **kw})


def test_vote_majority_agreement_and_counts():
    a, b = gfact(), gfact(person="Fenwick", place="The Library")  # same after normalising
    other = gfact(person="Captain Harlow", place="Ashby Grange", time_text="at noon", quote=Q2)
    out = vote([[a, other], [b], [gfact(time_text="at noon")]], TEXT)
    assert [f.person for f in out.kept] == ["Mr. Fenwick"]
    assert out.kept[0].votes == 2 and out.kept[0].samples == 3
    assert sorted(v for _, v in out.below) == [1, 1] and out.clusters == 3


def test_vote_polarity_quote_overlap_and_once_per_sample():
    a = gfact()
    assert vote([[a], [gfact(polarity="deny")]], TEXT).kept == []  # deny != affirm
    elsewhere = gfact(quote=Q2)  # same triple, quote elsewhere in the chunk
    assert vote([[a], [elsewhere]], TEXT).kept == []
    longer = gfact(quote="Lady Corbin retired early. " + Q1)  # overlaps the first >= 50%
    assert len(vote([[a], [longer]], TEXT).kept) == 1
    assert vote([[a, a, a], []], TEXT, 2).kept == []  # three copies in one sample are one vote
    assert len(vote([[a, a, a]], TEXT).kept) == 1


def test_failed_sample_counts_against_the_majority():
    a = gfact()
    assert vote([[a], []], TEXT, 3).kept == []  # 1 of 3 asked
    assert len(vote([[a], [a]], TEXT, 3).kept) == 1  # 2 of 3 asked


def test_samples_in_extractor_vote_cache_and_report():
    seq = [[good(), wrong()], [good()], [good(), wrong()]]
    client = make_client(seq, {"Mr. Fenwick": "yes", "Captain Harlow": "yes"})
    cache = ExtractCache()
    ex = extractor(client, cache, samples=3)
    res = run(ex)
    assert [f["person"] for f in res.facts] == ["Mr. Fenwick", "Captain Harlow"]
    assert [(f["votes"], f["samples"]) for f in res.facts] == [(3, 3), (2, 3)]
    assert res.voting["kept"] == 2 and res.voting["needed"] == 2
    extraction_calls = [c for c in client.calls if "Now the real case." not in c.prompt]
    assert [c.options["seed"] for c in extraction_calls] == [42, 43, 44]
    assert all(c.options["temperature"] == pytest.approx(0.3) for c in extraction_calls)
    # below majority: only one sample produced the fact
    client2 = make_client([[good()], [], []], {"Mr. Fenwick": "yes"})
    res2 = run(extractor(client2, samples=3))
    assert res2.facts == [] and res2.dropped[-1]["reason"] == "VOTE_BELOW_MAJORITY"
    assert res2.dropped[-1]["votes"] == 1 and res2.dropped[-1]["needed"] == 2
    # each sample is cached: nothing goes to the model again
    again = FakeClient(lambda p: 1 / 0)
    ex2 = extractor(again, cache, samples=3)
    assert [f["votes"] for f in run(ex2).facts] == [3, 2] and again.calls == []


# --- runner: flags, report, resume, determinism


def chunk_file(tmp_path):
    p = tmp_path / "chunks.jsonl"
    rec = {"chunk_id": "s-0001", "story": "s", "text": TEXT, "char_start": 0, "char_end": len(TEXT)}
    p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    return p


def test_runner_verify_samples_report_resume_and_determinism(tmp_path, capsys):
    args = ["--model", "fake:8b", "--chunks", str(chunk_file(tmp_path)), "--prompt", str(PROMPT_V1),
            "--cache", str(tmp_path / "c.sqlite"), "--out", str(tmp_path / "o.jsonl"),
            "--verify", "--verify-model", "fake:4b", "--samples", "3"]  # fmt: skip
    verdicts = {"Mr. Fenwick": "yes", "Captain Harlow": "wrong_person"}
    client = make_client([[good(), wrong()]], verdicts)
    assert presence.main(args, client=client) == 0
    rep = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rep["funnel"] == {"model": 2, "grounded": 2, "voted": 2, "verified": 1}
    assert rep["verify_rejected"] == 1 and rep["verify_rejected_by_detail"] == {"person_no": 1}
    assert rep["verify_calls"] == 2 and rep["samples"] == 3 and rep["verify_model"] == "fake:4b"
    vcalls = [c for c in client.calls if "Now the real case." in c.prompt]
    assert {c.model for c in vcalls} == {"fake:4b"} and len(client.calls) == 3 + 2
    first = (tmp_path / "o.jsonl").read_text()
    again = FakeClient(lambda p: 1 / 0)  # resumable: every extraction and verification is cached
    assert presence.main(args, client=again) == 0 and again.calls == []
    rep2 = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rep2["from_cache"] == 1 and rep2["verify_from_cache"] == 2
    second = json.loads((tmp_path / "o.jsonl").read_text())
    assert second["facts"] == json.loads(first)["facts"]  # deterministic


def test_runner_defaults_leave_extraction_unchanged(tmp_path, capsys):
    args = ["--model", "m", "--chunks", str(chunk_file(tmp_path)), "--prompt", str(PROMPT_V1),
            "--cache", str(tmp_path / "c.sqlite")]  # fmt: skip
    client = make_client([[good()]], {})
    assert presence.main(args, client=client) == 0
    rep = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert len(client.calls) == 1 and rep["verify"] is False and rep["samples"] == 1
    assert rep["funnel"] == {"model": 1, "grounded": 1, "voted": 1, "verified": 1}
