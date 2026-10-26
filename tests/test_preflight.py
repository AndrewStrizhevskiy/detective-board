import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parents[1] / "scripts" / "preflight.py"
)
pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pf)


def test_defaults_and_env_override():
    v = pf.effective(None, {})
    assert v["llm_model"] == "qwen3:4b-instruct" and v["embed_model"] == "bge-m3"
    assert pf.effective(None, {"DETECTIVE_BOARD_LLM_MODEL": "x:1b"})["llm_model"] == "x:1b"


def test_check_messages():
    v = pf.effective(None, {})
    assert "not reachable" in pf.check(v, None)[0]
    assert pf.check(v, ["qwen3:4b-instruct", "bge-m3:latest"]) == []
    out = pf.check(v, ["bge-m3:latest"])
    assert len(out) == 1 and "ollama pull qwen3:4b-instruct" in out[0]
