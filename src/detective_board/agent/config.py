"""Agent configuration. All thresholds are provisional ([P]) until the eval run."""

from __future__ import annotations

from dataclasses import dataclass

STRATEGIES = ("rank_full", "uniform")
ANSWER_MODES = ("extractive", "generate")
EXTRACT_ORDERS = ("score", "rank")


@dataclass(frozen=True)
class AgentConfig:
    top_k: int = 4  # chunks put into the prompt (prefill is ~11-23 tok/s on the target CPU)
    strategy: str = "rank_full"  # rank_full: top-1 chunk whole, others windows | uniform: windows
    window_words: int = 60  # query-focused window per shown excerpt (whole sentences)
    idf_chunks: str = ""  # chunks.jsonl for window word weights; empty = plain word overlap
    max_prompt_tokens: int = 1200  # estimate = chars/4, system prompt + facts + question included
    retry_extra_k: int = 2  # extra chunks fetched on the re-retrieve attempt
    min_score: float = 0.018  # RRF score of the best hit; ~ "present in both arms"
    min_support: float = 0.25  # share of question terms found in the best top-3 chunk
    max_graph_facts: int = 8
    max_tool_facts: int = 8
    max_retries: int = 1
    decline_retry: bool = True  # gate passed, model declined: one retry with a firmer instruction
    decline_fallback_min_support: float = 0.5  # gate support needed for the closest-passages answer
    min_quote_chars: int = 6
    min_claim_overlap: float = 0.3  # [P] content-word share of a claim held by its cited quotes
    memory_turns: int = 3
    memory_max_chars: int = 600
    use_llm_router: bool = False  # LLM classifier fallback when no rule matched
    tool_timeout_s: float = 5.0
    answer_mode: str = "extractive"  # extractive: the model picks sentences, text is a template
    # generate: the model writes a cited answer (kept for A/B)
    extract_top_k: int = 6  # extractive: chunks retrieved (the generative path uses top_k)
    extract_per_source: int = 8  # extractive: best-scoring sentences kept per chunk (whole text)
    extract_max_sentences: int = 40  # extractive: sentences offered to the model in total
    extract_max_tokens: int = 850  # extractive: prompt estimate; the lowest-scoring sentences go
    extract_order: str = (
        "score"  # what the sentence cap drops: "score" (lowest) | "rank" (worst chunks)
    )
    sentence_index_path: str = "data/index/sentences.sqlite"  # sentence hybrid index (optional)
    extract_sentence_k: int = 12  # extractive: top sentences of the whole-corpus sentence index
    extract_safety_chunks: int = 4  # ... plus the best sentences of this many top chunk hits
    extract_safety_per_chunk: int = 3  # (the former candidate builder, kept as a safety net)
    rule_first: bool = True  # rule questions: deterministic template from the rule result, no LLM
    scenes_path: str = ""  # curated crime scenes (data/curated/scenes.jsonl); "" = no board routing
    translate_questions: bool = True  # Cyrillic question -> English before everything else
    translate_model: str = "qwen3:4b-instruct"  # "translategemma:4b" is supported (own prompt)
    translate_max_chars: int = 300  # cap on the translated question
    translate_timeout_s: float = 30.0  # wall clock for the translation call
    translate_cache: str = ""  # JSONL file; empty = in-memory cache only
    # Neuro-symbolic R3 (agent/semantic_r3.py): when a contradiction question gets an empty rule
    # result, add a separate block of at most `semantic_r3_show` pairs a small model judged as
    # contradicting (hypotheses, not rule findings). OFF by default: not yet accepted (see docs).
    # On: AgentConfig(semantic_r3=True) or `--set semantic_r3=true` in eval/run_eval.py.
    semantic_r3: bool = False
    semantic_r3_max_pairs: int = 12  # candidate pairs judged per question
    semantic_r3_show: int = 2  # pairs shown
    temperature: float = 0.0
    seed: int = 42

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {STRATEGIES}, got {self.strategy!r}")
        if self.answer_mode not in ANSWER_MODES:
            raise ValueError(f"answer_mode must be one of {ANSWER_MODES}, got {self.answer_mode!r}")
        if self.extract_order not in EXTRACT_ORDERS:
            raise ValueError(f"extract_order must be one of {EXTRACT_ORDERS}")
