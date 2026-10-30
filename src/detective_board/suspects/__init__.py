"""Suspect board before the reveal (issue #21, docs/team/SUSPECTS_DESIGN_RU.md).

Candidates come from the graph (mentions before the cut), cheap closed-list LLM judgements are
grounded deterministically, and a deterministic matrix ranks the candidates. Every answer is a
`hypothesis`, never a verdict.
"""

NO_PERSON = "NO_PERSON"
