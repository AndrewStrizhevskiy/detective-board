"""Extractive mode with the sentence index: candidates from chunks that are NOT in the top chunk
hits, exact offsets, verbatim quotes, and the fallback when the index is absent."""

import json
import re

from detective_board.agent import AgentConfig, FakeLLM
from detective_board.agent.backends import HybridRetriever, SentenceResult
from detective_board.retrieval import EmbeddingConfig, HashEmbedder, Hit, Store
from detective_board.retrieval.sentences import SentenceHit, SentenceStore, split_sentences

from .conftest import T1, T2, FakeRetriever, hit, make_agent

Q = "What was the speckled band, and who guarded the vault on the night of the theft?"
OTHER = (
    "The rain fell steadily on the moor all day long. "
    "Old Perkins guarded the vault on the night of the theft, rifle across his knees. "
    "At dawn the doors were found open."
)
WANT = "Old Perkins guarded the vault on the night of the theft, rifle across his knees."
_LINE = re.compile(r"^(S\d+) \[source (\d+)\] (.*)$", re.M)


def chooser(snippet):
    def reply(messages):
        rows = _LINE.findall(messages[-1]["content"])
        return json.dumps({"choice": next((i for i, _, t in rows if snippet in t), "NONE")})

    return reply


class SentenceRetriever(FakeRetriever):
    """Chunk hits are T1, T2; the sentence index also knows a third chunk."""

    def __init__(self, hits, result):
        super().__init__(hits)
        self.result, self.sentence_calls = result, []

    def sentence_search(self, query, k):
        self.sentence_calls.append((query, k))
        return self.result


def other_result():
    chunk = hit(9, OTHER, 0.0)
    a = OTHER.index(WANT)
    sh = SentenceHit(77, chunk.chunk_id, chunk.story, a, a + len(WANT), WANT, 0.04, {"vec": 1})
    return SentenceResult([sh], {chunk.chunk_id: chunk}), chunk, a


def run(retriever, llm, cfg=None):
    agent = make_agent(llm, retriever, config=cfg or AgentConfig())
    return list(agent.ask(Q))


def test_sentence_from_a_chunk_outside_the_top_hits_is_chosen_and_quoted():
    res, chunk, a = other_result()
    r = SentenceRetriever([hit(1, T1), hit(2, T2)], res)
    llm = FakeLLM(chooser("Perkins"))
    ev = run(r, llm)
    fin = ev[-1]
    assert fin.status == "answered" and fin.verified
    assert fin.answer == f'From the sources: [1: "{WANT}"]'  # its chunk is the first source
    c = fin.citations[0]
    assert c.anchor.chunk_id == chunk.chunk_id and c.quote == WANT
    assert (c.anchor.char_start, c.anchor.char_end) == (
        chunk.char_start + a,
        chunk.char_start + a + len(WANT),
    )
    assert chunk.text[a : a + len(WANT)] == WANT
    eq = next(e for e in ev if e.type == "enriched_query")
    assert eq.strategy == "extractive + sentence index"
    assert [s.chunk_id for s in eq.sources][0] == chunk.chunk_id
    assert {s.chunk_id for s in eq.sources} <= {
        chunk.chunk_id,
        "speckled-band-0001",
        "speckled-band-0002",
    }
    assert r.sentence_calls == [(Q, AgentConfig().extract_sentence_k)]
    assert eq.prompt_tokens_estimate <= 850
    # the sentence hit comes first (hybrid score order), then the lexical safety net
    first = _LINE.findall(llm.calls[0][-1]["content"])[0]
    assert first[0] == "S1" and WANT in first[2]


def test_safety_net_keeps_the_best_sentences_of_the_top_two_chunks():
    res, chunk, _ = other_result()
    r = SentenceRetriever([hit(1, T1), hit(2, T2)], res)
    llm = FakeLLM(chooser("swamp adder"))
    ev = run(r, llm, AgentConfig())
    fin = ev[-1]
    assert fin.status == "answered" and "swamp adder" in fin.answer
    assert fin.citations[0].anchor.chunk_id == "speckled-band-0001"


def test_absent_index_falls_back_with_a_trace_note():
    r = SentenceRetriever([hit(1, T1), hit(2, T2)], None)
    ev = run(r, FakeLLM(chooser("swamp adder")))
    eq = next(e for e in ev if e.type == "enriched_query")
    assert "sentence index absent" in eq.strategy and eq.strategy.startswith("extractive")
    assert (
        ev[-1].status == "answered" and ev[-1].citations[0].anchor.chunk_id == "speckled-band-0001"
    )


def test_disabled_by_config_and_no_capability_keep_the_old_strategy():
    res, _, _ = other_result()
    r = SentenceRetriever([hit(1, T1), hit(2, T2)], res)
    ev = run(r, FakeLLM(chooser("swamp adder")), AgentConfig(extract_sentence_k=0))
    assert next(e for e in ev if e.type == "enriched_query").strategy == "extractive"
    assert r.sentence_calls == []
    ev = run(FakeRetriever([hit(1, T1), hit(2, T2)]), FakeLLM(chooser("swamp adder")))
    assert next(e for e in ev if e.type == "enriched_query").strategy == "extractive"


def test_a_failing_sentence_search_does_not_break_the_answer():
    class Boom(SentenceRetriever):
        def sentence_search(self, query, k):
            raise RuntimeError("index on fire")

    ev = run(Boom([hit(1, T1), hit(2, T2)], None), FakeLLM(chooser("swamp adder")))
    assert ev[-1].status == "answered"
    strategy = next(e for e in ev if e.type == "enriched_query").strategy
    assert "sentence search failed" in strategy


def test_stale_sentence_offsets_are_not_offered():
    res, chunk, a = other_result()
    bad = SentenceHit(78, chunk.chunk_id, chunk.story, a + 3, a + len(WANT), WANT, 0.05, {})
    r = SentenceRetriever([hit(1, T1), hit(2, T2)], SentenceResult([bad], res.chunks))
    llm = FakeLLM(chooser("Perkins"))
    ev = run(r, llm)
    assert ev[-1].status == "refused"  # the stale sentence is not on the list, nothing else matches
    assert "Perkins" not in llm.calls[0][-1]["content"]


def test_dedup_and_token_cap():
    res, chunk, a = other_result()
    dup = SentenceHit(5, "speckled-band-0001", "speckled-band", 0, len(T1), T1, 0.05, {})
    r = SentenceRetriever(
        [hit(1, T1), hit(2, T2)],
        SentenceResult([dup, *res.hits], {**res.chunks, "speckled-band-0001": hit(1, T1)}),
    )
    llm = FakeLLM(chooser("swamp adder"))
    run(r, llm)
    body = llm.calls[0][-1]["content"]
    assert body.count("swamp adder") == 1  # sentence-index copy and safety-net copy collapse


def test_real_hybrid_retriever_shares_the_query_embedding(tmp_path):
    cfg = EmbeddingConfig(model="fake", dim=64)

    class Counting(HashEmbedder):
        n = 0

        def embed_query(self, text):
            self.n += 1
            return super().embed_query(text)

    chunks = [hit(1, T1), hit(2, T2), hit(9, OTHER, 0.0)]
    emb = Counting(cfg)
    store = Store(":memory:", cfg)
    with store.db:
        for i, h in enumerate(chunks, 1):
            store.db.execute(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",
                (h.chunk_id, i, h.story, "I", 0, 0, h.char_start, h.char_end, h.text),
            )
        store.db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    sents = SentenceStore(":memory:", cfg)
    import sqlite_vec

    k = 0
    with sents.db:
        for h in chunks:
            for a, b in split_sentences(h.text):
                k += 1
                sents.db.execute(
                    "INSERT INTO sent VALUES (?,?,?,?,?,?)",
                    (k, h.chunk_id, h.story, a, b, h.text[a:b]),
                )
                sents.db.execute(
                    "INSERT INTO sent_vec(rowid, embedding) VALUES (?, ?)",
                    (k, sqlite_vec.serialize_float32(emb.embed_documents([h.text[a:b]])[0])),
                )
        sents.db.execute("INSERT INTO sent_fts(sent_fts) VALUES('rebuild')")
    retr = HybridRetriever(store, emb, sentences=sents)
    emb.n = 0
    found_chunks = retr.search(Q, 1)
    res = retr.sentence_search(Q, 12)
    assert emb.n == 1  # one embedding for both searches
    assert res is not None and res.hits[0].text == WANT
    assert res.chunks[res.hits[0].chunk_id].text == OTHER and len(found_chunks) == 1
    assert HybridRetriever(store, emb).sentence_search(Q, 12) is None
    assert isinstance(res.hits[0], SentenceHit) and isinstance(found_chunks[0], Hit)
