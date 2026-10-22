"""Raw-ASGI driver: a client that disconnects after N body chunks (TestClient cannot)."""

import asyncio
import json


async def stream_until_disconnect(app, body: dict, *, after_chunks: int, spec: str = "2.4"):
    chunks: list[bytes] = []
    gone = asyncio.Event()
    sent_body = False
    payload = json.dumps(body).encode()

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.body" and msg.get("body"):
            chunks.append(msg["body"])
            if len(chunks) >= after_chunks:
                gone.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/ask",
        "raw_path": b"/api/ask",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"localhost"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("localhost", 80),
    }
    try:
        await asyncio.wait_for(app(scope, receive, send), 10)
    except Exception:  # ClientDisconnect etc. is the expected outcome here
        pass
    return chunks
