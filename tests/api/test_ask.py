import asyncio
import threading
import time

import pytest
from pydantic import TypeAdapter
from starlette.testclient import TestClient

from detective_board.agent import FakeLLM
from detective_board.agent.events import TraceEvent
from detective_board.api import ApiConfig, build_app, fixture
from detective_board.api import app as app_mod

from .conftest import parse_sse
from .helpers import stream_until_disconnect

Q = {"question": "What was the speckled band?"}


def ask(client, body=Q):
    r = client.post("/api/ask", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


def test_sse_order_and_schema(client):
    evs = ask(client)
    names = [e["event"] for e in evs]
    assert names[:4] == [
        "route_decided",
        "retrieval_started",
        "retrieval_results",
        "enriched_query",
    ]
    assert names[-2:] == ["citation_check", "final"]
    assert "answer_token" in names
    assert [int(e["id"]) for e in evs] == list(range(len(evs)))  # id == seq, no gaps
    import json

    ta = TypeAdapter(TraceEvent)
    for e in evs:  # exactly the agent's models, one SSE event per trace event
        model = ta.validate_json(e["data"])
        assert model.type == e["event"] and model.seq == int(e["id"])
        assert model.model_dump_json() == e["data"]
    final = json.loads(evs[-1]["data"])
    assert final["status"] == "answered" and final["verified"]
    assert final["answer"].startswith("The band was a snake")
    assert final["citations"][0]["quote"] == "a deadly snake from India"
    assert final["citations"][0]["anchor"]["chunk_id"] == "speckled-band-0001"


def test_tokens_concatenate_to_answer(client):
    import json

    evs = ask(client)
    toks = "".join(json.loads(e["data"])["text"] for e in evs if e["event"] == "answer_token")
    assert toks.strip() == json.loads(evs[-1]["data"])["answer"]


def test_refusal_is_a_normal_event_stream(client):
    evs = ask(client, {"question": "What is the weather in Paris today?"})
    names = [e["event"] for e in evs]
    assert "refusal" in names and names[-1] == "final"
    import json

    assert json.loads(evs[-1]["data"])["status"] == "refused"


def test_history_accepted(client):
    evs = ask(client, {**Q, "history": [{"question": "Who is Holmes?", "answer": "A detective."}]})
    assert evs[-1]["event"] == "final"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": ""},
        {"question": 5},
        {"question": "x" * 1001},
        {"question": "ok", "extra": 1},
        {"question": "ok", "history": "no"},
        {"question": "ok", "history": [{"question": "a"}]},
        {"question": "ok", "history": [{"question": "a", "answer": "b"}] * 7},
        [],
    ],
)
def test_bad_requests_400(client, body):
    r = client.post("/api/ask", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_input"


def test_request_limits(client):
    assert (
        client.post("/api/ask", content=b"{}", headers={"content-type": "text/plain"}).status_code
        == 415
    )
    big = b'{"question": "' + b"a" * 20000 + b'"}'
    r = client.post("/api/ask", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"
    r = client.post("/api/ask", content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert client.get("/api/ask").status_code in (404, 405)  # never served as a page


class BoomLLM:
    def chat(self, messages, **kw):
        raise RuntimeError("secret internals /home/user/data.db")
        yield  # pragma: no cover

    generate = chat


def test_error_event_instead_of_stack_trace(cfg, monkeypatch):
    monkeypatch.setattr(fixture, "build_llm", lambda: BoomLLM())
    with TestClient(build_app(cfg), base_url="http://localhost") as c:
        r = c.post("/api/ask", json=Q)
        assert r.status_code == 200
        evs = parse_sse(r.text)
        assert evs[-1]["event"] == "run_error"
        assert "secret" not in r.text and "Traceback" not in r.text and "/home" not in r.text
        import json

        assert json.loads(evs[-1]["data"])["code"] == "internal"
        # earlier trace events were delivered before the failure
        assert evs[0]["event"] == "route_decided"
        # and the service recovers: the next run is accepted
        assert c.post("/api/ask", json={"question": "ok"}).status_code == 200


def test_unavailable_data_is_reported_as_error_event(tmp_path):
    cfg = ApiConfig(index_path=str(tmp_path / "missing.sqlite"), web_dir=str(tmp_path / "w"))
    with TestClient(build_app(cfg), base_url="http://localhost") as c:
        r = c.post("/api/ask", json=Q)
        evs = parse_sse(r.text)
        assert [e["event"] for e in evs] == ["run_error"]
        assert "unavailable" in evs[0]["data"] and str(tmp_path) not in r.text


class SlowLLM:
    """Streams 200 tokens at 10 ms each; counts how many were actually pulled."""

    def __init__(self):
        self.pulled = 0
        self.started = threading.Event()

    def chat(self, messages, **kw):
        self.started.set()
        for i in range(200):
            time.sleep(0.01)
            self.pulled += 1
            yield f"w{i} "

    generate = chat


@pytest.mark.parametrize("spec", ["2.4", "2.3"])
def test_client_disconnect_cancels_run(cfg, monkeypatch, spec):
    slow = SlowLLM()
    monkeypatch.setattr(fixture, "build_llm", lambda: slow)
    monkeypatch.setattr(app_mod, "POLL_S", 0.05)
    app = build_app(cfg)
    rt = app.state.runtime

    async def go():
        chunks = await stream_until_disconnect(app, Q, after_chunks=7, spec=spec)
        for _ in range(100):  # worker must stop long before 200 tokens (2 s)
            if not rt.busy:
                break
            await asyncio.sleep(0.05)
        return chunks

    chunks = asyncio.run(go())
    assert slow.started.is_set() and len(chunks) >= 7
    assert not rt.busy
    assert 0 < slow.pulled < 150
    rt.close()


def test_second_run_while_busy_gets_429(cfg, monkeypatch):
    slow = SlowLLM()
    monkeypatch.setattr(fixture, "build_llm", lambda: slow)
    app = build_app(cfg)
    rt = app.state.runtime
    with TestClient(app, base_url="http://localhost") as c:
        cancel = threading.Event()
        rt.start_run("What was the speckled band?", [], cancel, lambda item: None)
        assert slow.started.wait(5)
        r = c.post("/api/ask", json=Q)
        assert r.status_code == 429 and r.json()["error"]["code"] == "busy"
        cancel.set()
        for _ in range(100):
            if not rt.busy:
                break
            time.sleep(0.05)
        assert not rt.busy


def test_keepalive_comment_is_sent_while_waiting(cfg, monkeypatch):
    class Gap(FakeLLM):
        def chat(self, messages, **kw):
            time.sleep(0.8)
            return super().chat(messages, **kw)

    monkeypatch.setattr(fixture, "build_llm", lambda: Gap(fixture.FAKE_ANSWER))
    monkeypatch.setattr(app_mod, "POLL_S", 0.05)
    with TestClient(build_app(cfg), base_url="http://localhost") as c:  # keepalive_s=0.3
        r = c.post("/api/ask", json=Q)
        assert ": keepalive" in r.text and r.text.rstrip().endswith("}")
        assert parse_sse(r.text)[-1]["event"] == "final"


def test_fake_mode_derived_finding_has_explanation(client):
    import json
    from pathlib import Path

    evs = ask(client, {"question": "Are there contradictions in James McCarthy's account?"})
    by = {e["event"]: json.loads(e["data"]) for e in evs}
    tr = by["tool_result"]
    assert tr["ok"] and tr["provenance"] == "derived"
    exp = tr["explanation"]
    assert exp["rule_id"] == "R3" and exp["verdict"] == "violated" and exp["derivation"]
    final = by["final"]
    assert final["status"] == "answered" and final["verified"]
    derived = [p for p in final["provenance"] if p["label"] == "derived"]
    assert derived and all(p["rule_id"] == "R3" for p in derived)
    assert any(p["explanation"] == exp for p in final["provenance"])
    # quotes are verbatim in the real corpus text and resolvable through /api/source
    clean = Path(__file__).resolve().parents[2] / "data" / "clean" / (exp["anchors"][0]["story"])
    for a in exp["anchors"]:
        r = client.get(f"/api/source/{a['chunk_id']}", params={"quote": a["quote"]})
        assert r.status_code == 200 and r.json()["highlights"]
        text = clean.with_suffix(".txt")
        if text.exists():
            assert text.read_text(encoding="utf-8")[a["char_start"] : a["char_end"]] == a["quote"]
    ta = TypeAdapter(TraceEvent)
    for e in evs:
        assert ta.validate_json(e["data"]).model_dump_json() == e["data"]
