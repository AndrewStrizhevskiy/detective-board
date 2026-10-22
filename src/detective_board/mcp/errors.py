"""Error model of docs/mcp-contracts.md section 5."""

from __future__ import annotations

from typing import Any

CODES = (
    "invalid_input",
    "not_found",
    "ambiguous",
    "insufficient_evidence",
    "timeout",
    "store_unavailable",
    "internal",
)
_RETRIABLE = {"timeout": True, "store_unavailable": True}


class ToolError(Exception):
    """Raised inside tool functions; turned into the shared error object at the boundary."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        assert code in CODES, code
        self.code = code
        self.message = message
        self.details = details or {}

    def payload(self) -> dict[str, Any]:
        return error_payload(self.code, self.message, self.details)


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "retriable": _RETRIABLE.get(code, False),
            "details": details or {},
        }
    }
