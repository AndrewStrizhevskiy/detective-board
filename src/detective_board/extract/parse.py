"""Robust parsing of raw model output: strict JSON, deterministic truncation repair, per-item
validation. Valid items are kept; invalid ones are dropped with a recorded reason."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from detective_board.extract.schema_v2 import ITEM_MODELS, REPAIR_FIELDS

ParseStatus = Literal["ok", "repaired", "failed"]
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def repair_truncated(text: str) -> str | None:
    """Close a truncated top-level object `{"entities":[...],...}` deterministically.

    Cuts back to the last point where a top-level array was opened/closed or one of its items
    was completed, drops everything after it (the incomplete item, a dangling key or comma) and
    appends the closers. Returns None if there is no `{` at all.
    """
    start = text.find("{")
    if start < 0:
        return None
    stack: list[str] = []
    in_str = esc = False
    cut: tuple[int, list[str]] | None = None
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
            if ch == "[" and len(stack) == 2:
                cut = (i + 1, stack.copy())
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            if not stack:
                return text[start : i + 1]  # was complete
            if (ch == "}" and len(stack) == 2) or (ch == "]" and len(stack) == 1):
                cut = (i + 1, stack.copy())
    if cut is None:
        return "{}"
    pos, st = cut
    closers = "".join("]" if c == "[" else "}" for c in reversed(st))
    return text[start:pos] + closers


@dataclass
class ParsedOutput:
    data: dict | None
    status: ParseStatus
    error: str | None = None


def parse_output(raw: str) -> ParsedOutput:
    """Strict JSON first; on failure try fence-stripping, then truncation repair."""
    s = (raw or "").strip()
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            return ParsedOutput(d, "ok")
        return ParsedOutput(None, "failed", "top-level JSON is not an object")
    except ValueError as e:
        err = str(e)[:120]
    fixed = repair_truncated(_FENCE.sub("", s))
    if fixed is not None:
        try:
            d = json.loads(fixed)
            if isinstance(d, dict):
                return ParsedOutput(d, "repaired", err)
        except ValueError as e2:
            err = f"{err}; repair failed: {str(e2)[:80]}"
    return ParsedOutput(None, "failed", err)


@dataclass
class ItemReport:
    items: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    dropped: list[dict[str, Any]] = field(default_factory=list)


def _short(e: ValidationError) -> str:
    err = e.errors()[0]
    loc = ".".join(str(x) for x in err["loc"])
    return f"{err['type']}:{loc}"[:80]


def validate_items(data: dict) -> ItemReport:
    """Validate each item of each list on its own; unknown keys are stripped, not fatal."""
    rep = ItemReport(items={k: [] for k in ITEM_MODELS})
    for kind, model in ITEM_MODELS.items():
        raw_items = data.get(kind, [])
        if not isinstance(raw_items, list):
            rep.dropped.append({"kind": kind, "idx": -1, "reason": "not_a_list", "quote": None})
            continue
        known = set(model.model_fields) - REPAIR_FIELDS[kind]
        seen: set[str] = set()
        for idx, it in enumerate(raw_items):
            q = it.get("quote") if isinstance(it, dict) else None
            if not isinstance(it, dict):
                rep.dropped.append(
                    {"kind": kind, "idx": idx, "reason": "not_an_object", "quote": None}
                )
                continue
            try:
                obj = model.model_validate({k: v for k, v in it.items() if k in known})
            except ValidationError as e:
                rep.dropped.append({"kind": kind, "idx": idx, "reason": _short(e), "quote": q})
                continue
            if not obj.quote.strip():
                rep.dropped.append({"kind": kind, "idx": idx, "reason": "empty_quote", "quote": q})
                continue
            d = obj.model_dump()
            key = json.dumps(d, sort_keys=True, ensure_ascii=False)
            if key in seen:
                rep.dropped.append({"kind": kind, "idx": idx, "reason": "duplicate", "quote": q})
                continue
            seen.add(key)
            d["_idx"] = idx
            rep.items[kind].append(d)
    return rep
