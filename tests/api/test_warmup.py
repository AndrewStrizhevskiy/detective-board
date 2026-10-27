from detective_board.agent import FakeLLM
from detective_board.agent.context import SYSTEM_PROMPT
from detective_board.agent.extractive import SELECT_SYSTEM_PROMPT
from detective_board.api import ApiConfig
from detective_board.api.warmup import Warmup


class Emb:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def embed_query(self, t):
        self.calls.append(t)
        if self.fail:
            raise OSError("down")
        return [0.0]


def test_warmup_primes_system_prompt():
    llm = FakeLLM("x")
    w = Warmup(ApiConfig(agent={"answer_mode": "generate"}), llm=llm, embedder=Emb())
    w.run()
    s = w.status()
    assert s["state"] == "done" and s["embedding"] and s["llm"] and s["error"] is None
    assert llm.calls[0][0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_warmup_primes_the_selection_prompt_in_extractive_mode():
    llm = FakeLLM("x")
    Warmup(ApiConfig(), llm=llm, embedder=Emb()).run()
    assert llm.calls[0][0] == {"role": "system", "content": SELECT_SYSTEM_PROMPT}


def test_warmup_failure_is_not_fatal():
    class Bad:
        def chat(self, *a, **k):
            raise ConnectionError

    w = Warmup(ApiConfig(), llm=Bad(), embedder=Emb(fail=True))
    w.run()
    s = w.status()
    assert s["state"] == "failed" and s["llm"] is False and s["embedding"] is False
    assert "OSError" in s["error"] and "ConnectionError" in s["error"]


def test_warmup_skipped_in_fake_and_when_disabled():
    for cfg in (ApiConfig(fake=True), ApiConfig(warmup=False)):
        w = Warmup(cfg)
        assert w.start() is None and w.status()["state"] == "skipped"
