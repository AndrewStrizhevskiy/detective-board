"""Agent configuration. All thresholds are provisional ([P]) until the eval run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    top_k: int = 5  # chunks put into the prompt
    retry_extra_k: int = 3  # extra chunks fetched on the re-retrieve attempt
    min_score: float = 0.018  # RRF score of the best hit; ~ "present in both arms"
    min_support: float = 0.25  # share of question terms found in the best top-3 chunk
    max_graph_facts: int = 8
    max_tool_facts: int = 8
    max_retries: int = 1
    min_quote_chars: int = 6
    min_claim_overlap: float = 0.3  # [P] content-word share of a claim held by its cited quotes
    memory_turns: int = 3
    memory_max_chars: int = 600
    use_llm_router: bool = False  # LLM classifier fallback when no rule matched
    tool_timeout_s: float = 5.0
    temperature: float = 0.0
    seed: int = 42
