import pytest
from starlette.testclient import TestClient

from detective_board.api import ApiConfig, build_app, fixture

from .conftest import MODELS

SP = "speckled-band"


def test_subgraph_one_hop(client):
    d = client.get("/api/graph/subgraph", params={"entity": "Helen Stoner", "hops": 1}).json()
    assert d["seeds"] == [f"p:{SP}:helen-stoner"]
    names = {n["label"] for n in d["nodes"]}
    assert {"Helen Stoner", "Dr. Grimesby Roylott"} <= names
    assert "Julia Stoner" not in names
    n = next(n for n in d["nodes"] if n["label"] == "Helen Stoner")
    assert n["provenance"] == "extracted" and n["hops"] == 0 and n["anchors"]
    a = n["anchors"][0]
    assert {"story", "chunk_id", "char_start", "char_end", "quote"} <= set(a)
    (e,) = d["edges"]
    assert e["rel"] and e["provenance"] == "extracted" and e["anchor"]["quote"]
    assert {e["src"], e["dst"]} <= {x["id"] for x in d["nodes"]}
    assert d["anchors"] and d["truncated"] is False


def test_subgraph_hops_and_validation(client):
    z = client.get("/api/graph/subgraph", params={"entity": "Helen Stoner", "hops": 0}).json()
    assert len(z["nodes"]) == 1 and z["edges"] == []
    roy = client.get("/api/graph/entities", params={"q": "roylott"}).json()["entities"][0]["id"]
    two = client.get("/api/graph/subgraph", params={"entity": roy, "hops": 2})  # node id works
    assert two.status_code == 200 and two.json()["seeds"] == [roy]
    exact = client.get("/api/graph/subgraph", params={"entity": "Dr. Grimesby Roylott"}).json()
    assert exact["seeds"] == [roy]
    assert client.get("/api/graph/subgraph", params={"entity": "Nobody"}).json()["nodes"] == []
    for params in (
        {},
        {"entity": ""},
        {"entity": "x", "hops": "abc"},
        {"entity": "x", "hops": 99},
        {"entity": "x", "hops": -1},
        {"entity": "x" * 201},
        {"entity": "x", "story": "../etc"},
    ):
        r = client.get("/api/graph/subgraph", params=params)
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_input", params


def test_entities_search(client):
    d = client.get("/api/graph/entities", params={"q": "stoner"}).json()
    assert {e["label"] for e in d["entities"]} == {"Helen Stoner", "Julia Stoner"}
    assert d["entities"][0]["label"] == "Helen Stoner"  # more mentions first
    assert (
        client.get("/api/graph/entities", params={"q": "stoke", "kind": "place"}).json()["total"]
        == 1
    )
    assert (
        client.get("/api/graph/entities", params={"q": "stoke", "kind": "person"}).json()["total"]
        == 0
    )
    assert client.get("/api/graph/entities", params={"q": "%"}).json()["total"] == 0  # LIKE escaped
    allv = client.get("/api/graph/entities").json()
    assert (
        allv["total"] == 5
        and client.get("/api/graph/entities", params={"limit": 2}).json()["truncated"]
    )
    assert client.get("/api/graph/entities", params={"kind": "event"}).status_code == 400
    assert client.get("/api/graph/entities", params={"limit": 0}).status_code == 400


def test_source_and_highlights(client):
    cid = fixture.chunk_id(1)
    d = client.get(f"/api/source/{cid}", params={"quote": "a deadly snake from India"}).json()
    assert d["chunk_id"] == cid and d["text"].startswith("Holmes said") and d["contiguous"]
    (h,) = d["highlights"]
    assert d["text"][h["rel_start"] : h["rel_end"]] == "a deadly snake from India"
    assert h["char_start"] == d["char_start"] + h["rel_start"]
    ws = client.get(f"/api/source/{cid}", params={"quote": "deadly   snake"}).json()["highlights"]
    assert ws[0]["match"] == "ws_normalised"
    off = client.get(f"/api/source/{cid}", params={"start": 1000, "end": 1006}).json()["highlights"]
    assert off == [
        {"rel_start": 0, "rel_end": 6, "match": "offsets", "char_start": 1000, "char_end": 1006}
    ]
    assert (
        client.get(f"/api/source/{cid}", params={"quote": "absent words"}).json()["highlights"]
        == []
    )


def test_source_errors(client):
    assert client.get("/api/source/nope-0001").status_code == 404
    assert client.get("/api/source/bad$id").status_code == 400
    assert client.get("/api/source/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
    r = client.get("/api/source/speckled-band-0001", params={"start": "x"})
    assert r.status_code == 400


def test_health_fake(client):
    d = client.get("/api/health").json()
    assert d["status"] == "ok" and d["fake"] is True
    assert d["index"] == {"present": True, "chunks": 5, "vectors": 5}
    assert d["graph"]["present"] and d["graph"]["counts"]["edges"] == 1
    assert d["ollama"]["reachable"] is None
    assert d["versions"]["starlette"] and d["versions"]["index_schema"]


def _real_cfg(tmp_path, **kw):
    return ApiConfig(
        index_path=str(tmp_path / "i.sqlite"),
        graph_path=str(tmp_path / "g.sqlite"),
        embed_model="fake-hash",
        embed_dim=64,
        embed_doc_prefix="doc: ",
        embed_query_prefix="q: ",
        llm_model="qwen3:8b",
        web_dir=str(tmp_path / "w"),
        **kw,
    )


def test_health_degraded_without_data_or_models(tmp_path):
    cfg = _real_cfg(tmp_path)
    for probe, reachable in ((lambda: None, False), (lambda: ["other:1b"], True)):
        with TestClient(build_app(cfg, ollama_probe=probe), base_url="http://localhost") as c:
            d = c.get("/api/health").json()
            assert d["status"] == "degraded"
            assert d["index"]["present"] is False and d["graph"]["present"] is False
            assert d["ollama"]["reachable"] is reachable
            assert str(tmp_path) not in str(d)  # no filesystem paths leak


def test_real_wiring_on_files(tmp_path):
    """Non-fake build_app on file-backed stores (fixture data; embedder is never called)."""
    store, _ = fixture.build_store(str(tmp_path / "i.sqlite"))
    store.close()
    fixture.build_graph(str(tmp_path / "g.sqlite")).close()
    cfg = _real_cfg(tmp_path)
    with TestClient(
        build_app(cfg, ollama_probe=lambda: MODELS[:1] + ["fake-hash"]), base_url="http://localhost"
    ) as c:
        d = c.get("/api/health").json()
        assert d["status"] == "ok", d
        assert d["index"]["chunks"] == 5 and d["ollama"]["models"] == {
            "llm": True,
            "embedding": True,
        }
        assert c.get("/api/source/speckled-band-0002").json()["story"] == SP
        assert c.get("/api/graph/entities", params={"q": "julia"}).json()["total"] == 1


def test_config_endpoint(client, cfg):
    d = client.get("/api/config").json()
    assert d["fake"] is True and d["models"]["llm"] == "fake"
    assert d["agent"]["min_score"] == 0.018 and d["limits"]["max_body_bytes"] == 16384
    assert "final" in d["events"] and "run_error" in d["events"]
    assert "path" not in str(d).lower() and cfg.web_dir not in str(d)


def test_static_and_api_404(client):
    r = client.get("/")
    assert r.status_code == 200 and "hi" in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.get("/..%2f..%2fetc/passwd").status_code == 404


def test_no_cors_and_host_guard(cfg):
    app = build_app(cfg)
    with TestClient(app, base_url="http://localhost") as c:
        r = c.get("/api/config", headers={"origin": "http://evil.example"})
        assert "access-control-allow-origin" not in r.headers
        assert c.options("/api/ask", headers={"origin": "http://evil.example"}).status_code in (
            404,
            405,
        )
    with TestClient(app, base_url="http://evil.example") as c:  # DNS-rebinding guard
        assert c.get("/api/config").status_code == 400


@pytest.mark.parametrize("path", ["/api/graph/subgraph?entity=x&hops=1", "/api/graph/entities"])
def test_graph_endpoints_do_not_block_on_busy_agent(client, path):
    assert client.get(path).status_code == 200


def test_subgraph_derived_edge_exposes_explanation():
    import json

    from detective_board.api import graph_view

    g = fixture.build_graph()
    exp = fixture.boscombe_explanation().model_dump(mode="json")
    g.conn.execute(
        "UPDATE g_edge SET provenance='derived', props_json=?", (json.dumps({"explanation": exp}),)
    )
    d = graph_view.subgraph(g, "Helen Stoner", 1, story=None, max_nodes=50)
    (e,) = d["edges"]
    assert e["provenance"] == "derived" and e["explanation"] == exp
    g.conn.execute("UPDATE g_edge SET props_json=?", (json.dumps({"explanation": {"bad": 1}}),))
    (e,) = graph_view.subgraph(g, "Helen Stoner", 1, story=None, max_nodes=50)["edges"]
    assert "explanation" not in e
    g.conn.execute("UPDATE g_edge SET provenance='extracted'")
    (e,) = graph_view.subgraph(g, "Helen Stoner", 1, story=None, max_nodes=50)["edges"]
    assert "explanation" not in e
