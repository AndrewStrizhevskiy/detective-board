"""Honesty guard for rule questions: absence of a finding is not absence of a conflict.

`asserts_consistency` finds statements that present an empty or failed rule result as proof that
the accounts agree. It is applied to the claim text only (never to quoted source text), and a
negated use ("this does not show that the accounts are consistent") is not a match.
"""

from __future__ import annotations

import re

ASSERT_PATTERNS = (
    r"\bno\s+(?:\w+\s+){0,2}(?:conflicts?|contradictions?|inconsistenc\w+|discrepanc\w+)\b",
    r"\bnot?\s+(?:any\s+)?(?:conflicts?|contradictions?|inconsistenc\w+|discrepanc\w+)\b",
    r"\b(?:does|do|did)(?:\s+not|n['’]t)\s+(?:conflict|contradict)",
    r"\bnothing\s+(?:conflicts?|contradicts?)\b",
    r"\bwithout\s+(?:any\s+)?(?:conflicts?|contradictions?|inconsisten\w+)\b",
    r"\b(?:consistent|compatible|coherent|in agreement|agree[sd]?)\b",
    r"\b(?:no|nothing)\s+(?:\w+\s+){0,2}(?:wrong|amiss|suspicious)\b",
)
_RX = tuple(re.compile(p, re.I) for p in ASSERT_PATTERNS)
_NEGATION = re.compile(
    r"\b(?:not|never|cannot|neither|nor|without proof|no evidence|n['’]t)\b[^.;:!?]*$", re.I
)
_CLAUSE = 60


def asserts_consistency(text: str) -> list[str]:
    """Snippets of `text` that assert consistency or absence of conflict (empty list: none)."""
    out: list[str] = []
    for rx in _RX:
        for m in rx.finditer(text):
            before = text[max(0, m.start() - _CLAUSE) : m.start()]
            if m.group(0).lower().startswith(("no", "not", "nothing", "without")):
                out.append(m.group(0))  # the match carries its own quantifier
                continue
            if _NEGATION.search(before):
                continue
            out.append(m.group(0))
    return list(dict.fromkeys(out))


GUARD_PROBLEM = (
    "asserts consistency or absence of conflict, but the rule result is empty or failed: "
    "an empty result does not show that the accounts agree; say only that no rule finding was "
    "produced"
)
