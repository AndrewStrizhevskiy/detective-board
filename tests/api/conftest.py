import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from starlette.testclient import TestClient  # noqa: E402

from detective_board.api import ApiConfig, build_app  # noqa: E402

MODELS = ["qwen3:8b", "bge-m3:latest"]


@pytest.fixture
def cfg(tmp_path) -> ApiConfig:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<p>hi</p>")
    return ApiConfig(fake=True, web_dir=str(web), keepalive_s=0.3)


@pytest.fixture
def client(cfg):
    app = build_app(cfg, ollama_probe=lambda: MODELS)
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        ev = {"data": []}
        for line in block.split("\n"):
            if line.startswith(":"):
                ev.setdefault("comments", []).append(line)
            elif line.startswith("data: "):
                ev["data"].append(line[6:])
            elif ": " in line:
                k, v = line.split(": ", 1)
                ev[k] = v
        ev["data"] = "\n".join(ev["data"])
        out.append(ev)
    return out
