"""Rule registry: adding a rule = a function + id + version + tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from detective_board.symbolic.facts import FactBase
from detective_board.symbolic.model import RULE_VERSIONS, Report
from detective_board.symbolic.rules import r1_presence, r2_order, r3_claims


@dataclass(frozen=True)
class Rule:
    id: str
    version: str
    run: Callable[[FactBase], Report]


RULES: dict[str, Rule] = {
    "R1": Rule("R1", RULE_VERSIONS["R1"], lambda fb: r1_presence.scan_presence_conflicts(fb)),
    "R2": Rule("R2", RULE_VERSIONS["R2"], lambda fb: r2_order.find_order_cycles(fb)),
    "R3": Rule("R3", RULE_VERSIONS["R3"], lambda fb: r3_claims.scan_claims(fb)),
}
