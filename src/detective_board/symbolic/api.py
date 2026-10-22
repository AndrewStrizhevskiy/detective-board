"""Public entry points: the only module the agent and the MCP server import."""

from __future__ import annotations

from detective_board.symbolic.facts import (
    ClaimRec,
    EventRec,
    FactBase,
    OrderProp,
    PlaceRec,
    PresenceProp,
    load_facts,
)
from detective_board.symbolic.model import (
    Anchor,
    EdgeRef,
    Explanation,
    FactRef,
    FactSource,
    Finding,
    Report,
    Step,
    TimeSpec,
    Verdict,
)
from detective_board.symbolic.rules import RULES
from detective_board.symbolic.rules.r1_presence import check_presence, scan_presence_conflicts
from detective_board.symbolic.rules.r2_order import find_order_cycles, order_of, timeline
from detective_board.symbolic.rules.r3_claims import check_claim, scan_claims


def run_all(fb: FactBase, rules: tuple[str, ...] = ("R1", "R2", "R3")) -> list[Report]:
    unknown = [r for r in rules if r not in RULES]
    if unknown:
        raise ValueError(f"unknown rule ids: {unknown}")
    return [RULES[r].run(fb) for r in rules]


__all__ = [
    "Anchor",
    "ClaimRec",
    "EdgeRef",
    "EventRec",
    "Explanation",
    "FactBase",
    "FactRef",
    "FactSource",
    "Finding",
    "OrderProp",
    "PlaceRec",
    "PresenceProp",
    "Report",
    "Step",
    "TimeSpec",
    "Verdict",
    "check_claim",
    "check_presence",
    "find_order_cycles",
    "load_facts",
    "order_of",
    "run_all",
    "scan_claims",
    "scan_presence_conflicts",
    "timeline",
]
