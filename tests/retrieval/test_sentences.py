"""Sentence index: splitting offsets, hybrid search with hand-computed RRF."""

import json

import pytest
import sqlite_vec

from detective_board.agent.window import sentence_spans
from detective_board.retrieval import EmbeddingConfig
from detective_board.retrieval.sentences import (
    RRF_K,
    RRF_WEIGHTS,
    SentenceIndexError,
    SentenceStore,
    iter_sentences,
    sentence_search,
    split_sentences,
)

CHUNKS = "data/chunks.jsonl"


def test_offsets_round_trip_on_real_chunks():
    """Every sentence is exactly chunk.text[start:end], trimmed, in order, no overlap."""
    n = 0
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            t, last = c["text"], 0
            for a, b in split_sentences(t):
                assert last <= a < b <= len(t) and t[a:b] == t[a:b].strip() and t[a:b]
                assert len(t[a:b].split()) >= 4
                last = b
                n += 1
    assert n > 5000


def test_short_units_merge_into_the_next_sentence():
    t = 'He nodded. "Yes." "I saw him at the door." It was already very dark.'
    assert [t[a:b] for a, b in split_sentences(t)] == [
        'He nodded. "Yes." "I saw him at the door."',
        "It was already very dark.",
    ]
    # nothing is dropped: the units tile the text apart from the whitespace between them
    assert sentence_spans(t)[0][0] == split_sentences(t)[0][0]


def test_trailing_short_unit_joins_the_previous_sentence_and_tiny_chunks_yield_nothing():
    t = "The lamp burned low all night. Quiet."
    assert [t[a:b] for a, b in split_sentences(t)] == [t]
    assert split_sentences("Yes. No.") == []
    assert split_sentences("") == []


def test_iter_sentences_carries_chunk_identity():
    rows = list(iter_sentences([{"chunk_id": "s-0", "story": "s", "text": "One two three four."}]))
    assert rows == [("s-0", "s", 0, 19, "One two three four.")]


CFG = EmbeddingConfig(model="fake", dim=4)
SENTS = [  # id, chunk, text, vector
    (1, "c-1", "The snake was a swamp adder.", [1, 0, 0, 0]),
    (2, "c-2", "A cheetah roamed the grounds.", [0.6, 0.8, 0, 0]),
    (3, "c-3", "The snake slid down the long dark rope tonight.", [0.2, 0.98, 0, 0]),
    (4, "c-4", "Nothing else was said about it.", [0, 0, 1, 0]),
]


@pytest.fixture
def store():
    st = SentenceStore(":memory:", CFG)
    with st.db:
        for i, c, t, v in SENTS:
            st.db.execute(
                "INSERT INTO sent(id, chunk_id, story, start, end, text) VALUES (?,?,?,?,?,?)",
                (i, c, "s", 10 * i, 10 * i + len(t), t),
            )
            st.db.execute(
                "INSERT INTO sent_vec(rowid, embedding) VALUES (?, ?)",
                (i, sqlite_vec.serialize_float32(v)),
            )
        st.db.execute("INSERT INTO sent_fts(sent_fts) VALUES('rebuild')")
    return st


def test_hybrid_search_matches_hand_computed_rrf(store):
    # BM25 arm for "snake" (OR mode): s1 (6 words) before s3 (9 words): ranks 1, 2.
    # Vector arm, cosine to [1,0,0,0], k_vec=3: s1 (0), s2 (0.4), s3 (~0.8): ranks 1, 2, 3.
    # RRF with k=30, weights bm25 0.5 / vec 1:
    s1 = 0.5 / 31 + 1 / 31
    s2 = 1 / 32
    s3 = 0.5 / 32 + 1 / 33
    assert RRF_K == 30 and RRF_WEIGHTS == {"bm25": 0.5, "vec": 1.0}
    hits = sentence_search(store, "snake", [1, 0, 0, 0], k_vec=3, k_bm25=5, k=10)
    assert [h.id for h in hits] == [1, 3, 2]  # s3 (0.0459) beats s2 (0.03125)
    assert [h.score for h in hits] == pytest.approx([s1, s3, s2])
    h1 = hits[0]
    assert (h1.chunk_id, h1.story, h1.start, h1.end) == ("c-1", "s", 10, 38)
    assert h1.text == SENTS[0][2] and h1.ranks == {"bm25": 1, "vec": 1}
    assert hits[1].ranks == {"bm25": 2, "vec": 3} and hits[2].ranks == {"vec": 2}
    assert h1.scores["vec"] == pytest.approx(0.0, abs=1e-6)
    assert hits[2].scores["vec"] == pytest.approx(0.4, abs=1e-4)
    assert [h.id for h in sentence_search(store, "snake", [1, 0, 0, 0], 3, 5, k=2)] == [1, 3]


def test_search_arms_alone_and_query_escaping(store):
    only_bm25 = sentence_search(store, "snake", None, 5, 5, 5)
    assert [h.id for h in only_bm25] == [1, 3] and all(set(h.ranks) == {"bm25"} for h in only_bm25)
    # FTS operators and quotes in the question are neutralised; nothing to search -> []
    assert sentence_search(store, 'snake" OR NOT (', None, 5, 5, 5)
    assert sentence_search(store, "?!", None, 5, 5, 5) == []
    assert [h.id for h in sentence_search(store, "???", [0, 0, 1, 0], 1, 5, 5)] == [4]


def test_incompatible_manifest_is_refused(tmp_path):
    p = tmp_path / "s.sqlite"
    SentenceStore(p, CFG).close()
    with pytest.raises(SentenceIndexError):
        SentenceStore(p, EmbeddingConfig(model="other", dim=4))
