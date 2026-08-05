"""HTTP / pipeline response models for document parse."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocParseMeta(BaseModel):
    source_filename: str
    segment_prompt_hash: str
    block_count: int = 0
    batch_count: int = 0
    parse_quality: str | None = None
    parse_backend: str | None = Field(
        default=None,
        description="Primary document parser: docling or markitdown (fallback)",
    )
    warnings: list[str] = Field(default_factory=list)
    parse_ms: int | None = Field(default=None, description="Physical file → markdown time (ms)")
    block_ms: int | None = Field(default=None, description="Markdown split + batch pack time (ms)")
    llm_ms: int | None = Field(default=None, description="LLM batch calls + merge time (ms)")
    total_ms: int | None = Field(default=None, description="End-to-end pipeline time (ms)")


class DocParseResponse(BaseModel):
    """Envelope: business payload in ``data``, platform fields in ``meta``."""

    data: Any = Field(description="JSON produced by the model per segment_prompt")
    meta: DocParseMeta
