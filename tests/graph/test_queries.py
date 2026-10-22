from .conftest import C2, C3, STORY

P = f"p:{STORY}:"


def test_find_entities_by_name_alias_title_possessive(bv):
    for q in ("Charles McCarthy", "Mr. McCarthy", "McCarthy's", "mccarthy"):
        assert bv.find_entities(q, kind="person").node_ids == [P + "charles-mccarthy"], q
    assert bv.find_entities("Dr. Turner").node_ids == [P + "john-turner"]
    assert bv.find_entities("Boscombe Pool").nodes[0].kind == "place"
    assert bv.find_entities("Nobody").nodes == []
    assert bv.find_entities(P + "john-turner").node_ids == [P + "john-turner"]  # by id
    assert bv.find_entities("Turner", story="other").nodes == []


def test_events_by_person_and_place(bv):
    r = bv.events_by_person("Charles McCarthy")
    evs = [n for n in r.nodes if n.kind == "event"]
    assert [n.id for n in evs] == [f"e:{C2}:0", f"e:{C3}:0"]  # text order
    assert {e.rel for e in r.edges} == {"PARTICIPATED_IN", "OCCURRED_AT"}
    assert r.nodes[0].id == P + "charles-mccarthy"  # seed first
    by_place = bv.events_by_place("the Boscombe Pool")
    assert [n.id for n in by_place.nodes if n.kind == "event"] == [f"e:{C2}:0", f"e:{C3}:0"]
    assert bv.events_by_person("Nobody").nodes == []
    assert all(e.anchor.quote for e in r.edges) and r.anchors


def test_claims_by_speaker(bv):
    r = bv.claims_by_speaker("James McCarthy")
    claims = [n for n in r.nodes if n.kind == "claim"]
    assert len(claims) == 1 and "Hatherley" in claims[0].props["content"]
    assert {e.rel for e in r.edges} == {"ASSERTS", "ABOUT"}
    assert claims[0].anchors[0].quote.startswith("I left him")


def test_neighbours_khop_and_determinism(bv, chunks):
    from .conftest import build_boscombe

    r1 = bv.neighbours("James McCarthy", k=1)
    assert {n.id for n in r1.nodes if n.hops == 1} == {
        f"e:{C3}:0",
        f"c:{'boscombe-valley-mystery-0007'}:0",
    }
    r2 = bv.neighbours("James McCarthy", k=2)
    hop2 = {n.id for n in r2.nodes if n.hops == 2}
    assert {f"pl:{STORY}:boscombe-pool", f"pl:{STORY}:hatherley", P + "patience-moran"} <= hop2
    assert r2.nodes[0].hops == 0 and [n.hops for n in r2.nodes] == sorted(n.hops for n in r2.nodes)
    assert r2.edge_ids == sorted(r2.edge_ids)
    assert bv.neighbours("James McCarthy", k=2) == r2  # repeat
    assert build_boscombe(chunks).neighbours("James McCarthy", k=2) == r2  # fresh identical store
    assert bv.neighbours("James McCarthy", k=0).nodes[0].hops == 0
    only = bv.neighbours("James McCarthy", k=2, rels=["ASSERTS", "ABOUT"])
    assert {e.rel for e in only.edges} == {"ASSERTS", "ABOUT"}
    out = bv.neighbours("James McCarthy", k=1, direction="in")
    assert {n.id for n in out.nodes} == {P + "james-mccarthy"}
    capped = bv.neighbours("James McCarthy", k=3, max_nodes=3)
    assert capped.truncated and len(capped.nodes) == 3


def test_shortest_path(bv):
    r = bv.shortest_path("Patience Moran", "Hatherley")
    assert r.found and r.hops == 4
    assert [n.kind for n in r.nodes] == ["person", "event", "person", "claim", "place"]
    assert r.nodes[2].id == P + "james-mccarthy"
    assert len(r.edges) == 4 and all(e.anchor.quote for e in r.edges)
    for i, e in enumerate(r.edges):  # consecutive nodes are the edge endpoints
        assert {e.src, e.dst} == {r.nodes[i].id, r.nodes[i + 1].id}
    assert bv.shortest_path("Patience Moran", "Hatherley") == r
    assert bv.shortest_path("Patience Moran", "Hatherley", max_hops=2).found is False
    same = bv.shortest_path("John Turner", "Turner")
    assert same.found and same.hops == 0
    assert bv.shortest_path("John Turner", "Nobody").found is False
    short = bv.shortest_path("John Turner", "Charles McCarthy")
    assert short.hops == 1 and short.edges[0].rel == "RELATION"
    assert short.edges[0].props == {"predicate": "tenant of"}


def test_trace_payload(bv):
    r = bv.neighbours("John Turner", k=1)
    p = r.trace_payload()
    assert set(p) == {"query_kind", "seeds", "nodes", "edges", "truncated"}
    assert [n["id"] for n in p["nodes"]] == r.node_ids
    assert all(e["anchor"]["chunk_id"] for e in p["edges"])
    assert [a.char_start for a in r.anchors] == sorted(a.char_start for a in r.anchors)
