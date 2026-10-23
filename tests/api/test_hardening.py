"""Regression tests for docs/security.md findings 3.1-3.3, 4 (CSP)."""

import re

from starlette.testclient import TestClient

from detective_board.api import build_app

from .conftest import MODELS

ASK = {"question": "What was the speckled band?"}


def _client(cfg, base="http://localhost"):
    return TestClient(build_app(cfg, ollama_probe=lambda: MODELS), base_url=base)


def test_security_headers_and_csp(client):
    for path in ("/", "/api/health", "/api/nope"):
        h = client.get(path).headers
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp
        assert "object-src 'none'" in csp and "base-uri 'none'" in csp
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"


def test_real_index_has_no_inline_script_or_style():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.I)
    assert not re.search(r"<style|\sstyle\s*=|\son\w+\s*=|javascript:", html, re.I)


def test_ipv6_loopback_host_accepted(cfg):
    with _client(cfg, "http://[::1]:8000") as c:
        assert c.get("/api/health").status_code == 200
    with _client(cfg, "http://evil.example") as c:
        assert c.get("/api/health").status_code == 400
    with _client(cfg) as c:
        assert c.get("/api/health", headers={"host": "[::1]:8000"}).status_code == 200
        assert c.get("/api/health", headers={"host": "[::2]:8000"}).status_code == 400
        assert c.get("/api/health", headers={"host": "localhost.evil.example"}).status_code == 400


def test_origin_check_on_ask(client):
    ok = client.post("/api/ask", json=ASK, headers={"origin": "http://localhost"})
    assert ok.status_code == 200
    assert client.post("/api/ask", json=ASK).status_code == 200  # no Origin: curl, tests
    for origin in (
        "http://evil.example",
        "null",
        "http://localhost.evil.example",
        "http://localhost:9999",
    ):
        r = client.post("/api/ask", json=ASK, headers={"origin": origin})
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_origin", origin
    r = client.post("/api/ask", json=ASK, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
