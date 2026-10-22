"""Server-Sent Events framing (WHATWG HTML section 9.2): `event:`, `id:`, `data:`, blank line."""

from __future__ import annotations

KEEPALIVE = b": keepalive\n\n"


def frame(event: str, data: str, id: str | int | None = None) -> bytes:
    """One SSE message. `event` and `id` must be single-line; `data` may contain newlines
    (each line gets its own `data:` field, as the format requires)."""
    if "\n" in event or "\r" in event or (id is not None and ("\n" in str(id) or "\r" in str(id))):
        raise ValueError("event name and id must be single-line")
    lines = [f"event: {event}"]
    if id is not None:
        lines.append(f"id: {id}")
    lines += [
        f"data: {part}" for part in data.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return ("\n".join(lines) + "\n\n").encode()
