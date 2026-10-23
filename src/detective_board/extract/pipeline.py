"""Per-chunk extraction: prompt -> (cache | LLM) -> parse/repair -> validate -> ground."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from detective_board.extract import schema_v2
from detective_board.extract.cache import ExtractCache, cache_key
from detective_board.extract.ground import ground_quote, normalise
from detective_board.extract.llm import GenRequest, LLMClient
from detective_board.extract.parse import parse_output, validate_items

PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts" / "extract"
DEFAULT_PROMPT = PROMPT_DIR / "extract_v2_1.txt"
CHUNK_MARK = "{{CHUNK}}"


@dataclass(frozen=True)
class Prompt:
    version: str
    template: str

    def render(self, chunk: str) -> str:
        return self.template.replace(CHUNK_MARK, chunk)


def load_prompt(path: str | Path = DEFAULT_PROMPT) -> Prompt:
    head, sep, body = Path(path).read_text(encoding="utf-8").partition("\n---\n")
    if not sep or not head.startswith("version:"):
        raise ValueError(f"{path}: expected 'version: X' header followed by '---'")
    if CHUNK_MARK not in body:
        raise ValueError(f"{path}: template lacks {CHUNK_MARK}")
    return Prompt(head.split(":", 1)[1].strip(), body)


@dataclass(frozen=True)
class ExtractConfig:
    model: str
    num_ctx: int = 4096
    num_predict: int = 1536
    seed: int = 42
    temperature: float = 0.0
    fuzzy_threshold: float = 0.85
    keep_ungrounded: bool = False

    def options(self) -> dict[str, Any]:
        """Generation options; part of the cache key."""
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
        }


@dataclass
class ChunkResult:
    chunk_id: str
    story: str
    status: str  # ok | repaired | failed | error
    extraction: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    grounding: dict[str, int] = field(default_factory=lambda: {"exact": 0, "fuzzy": 0, "none": 0})
    truncated: bool = False  # model hit the token cap (done_reason == "length")
    cached: bool = False
    wall_s: float = 0.0  # LLM wall time of the original call
    error: str | None = None
    model: str = ""
    prompt_version: str = ""
    schema_version: str = schema_v2.SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id, "story": self.story, "status": self.status,
            "truncated": self.truncated, "cached": self.cached, "wall_s": self.wall_s,
            "error": self.error, "model": self.model, "prompt_version": self.prompt_version,
            "schema_version": self.schema_version, "grounding": self.grounding,
            "dropped": self.dropped, "extraction": self.extraction,
        }  # fmt: skip

    def to_extraction(self) -> schema_v2.Extraction:
        """The kept items as a validated v2 extraction (bookkeeping keys stripped)."""
        return schema_v2.Extraction.model_validate(
            {
                k: [
                    {a: b for a, b in it.items() if a in schema_v2.ITEM_MODELS[k].model_fields}
                    for it in items
                ]
                for k, items in self.extraction.items()
            }
        )


class Extractor:
    def __init__(
        self,
        client: LLMClient,
        cfg: ExtractConfig,
        cache: ExtractCache | None = None,
        prompt: Prompt | None = None,
    ) -> None:
        self.client = client
        self.cfg = cfg
        self.cache = cache
        self.prompt = prompt or load_prompt()
        self._schema = schema_v2.ollama_format_schema()

    def key(self, text: str) -> str:
        return cache_key(
            text, self.cfg.model, self.prompt.version, schema_v2.SCHEMA_VERSION, self.cfg.options()
        )

    def _raw(self, text: str) -> tuple[dict | None, bool, str | None]:
        """(raw record, from_cache, error)."""
        key = self.key(text)
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            return hit, True, None
        req = GenRequest(self.cfg.model, self.prompt.render(text), self._schema, self.cfg.options())
        try:
            r = self.client.generate(req)
        except Exception as e:  # network/model error: not cached, chunk marked error
            return None, False, f"{type(e).__name__}: {str(e)[:200]}"
        rec = {"text": r.text, "done_reason": r.done_reason, "gen_tokens": r.gen_tokens,
               "prompt_tokens": r.prompt_tokens, "wall_s": r.wall_s}  # fmt: skip
        if self.cache is not None:
            self.cache.put(key, rec)
        return rec, False, None

    def extract_chunk(self, chunk_id: str, story: str, text: str) -> ChunkResult:
        res = ChunkResult(
            chunk_id, story, "error", model=self.cfg.model, prompt_version=self.prompt.version
        )
        rec, cached, err = self._raw(text)
        if rec is None:
            res.error = err
            return res
        res.cached, res.wall_s = cached, float(rec.get("wall_s") or 0.0)
        res.truncated = rec.get("done_reason") == "length"
        parsed = parse_output(rec["text"])
        res.status, res.error = parsed.status, parsed.error
        if parsed.data is None:
            return res
        rep = validate_items(parsed.data)
        res.dropped = list(rep.dropped)
        chunk_n = normalise(text)
        for kind, items in rep.items.items():
            kept = []
            for it in items:
                idx = it.pop("_idx")
                g = ground_quote(it["quote"], chunk_n, threshold=self.cfg.fuzzy_threshold)
                res.grounding[g.grounded] += 1
                if g.grounded == "none" and not self.cfg.keep_ungrounded:
                    res.dropped.append(
                        {
                            "kind": kind,
                            "idx": idx,
                            "reason": "quote_not_grounded",
                            "quote": it["quote"],
                        }
                    )
                    continue
                if g.span is not None:
                    if g.grounded == "fuzzy":
                        it["quote_model"] = it["quote"]
                        it["fuzzy_ratio"] = g.ratio
                    it["quote"] = g.span
                it["grounded"] = g.grounded
                kept.append(it)
            res.extraction[kind] = kept
        return res
