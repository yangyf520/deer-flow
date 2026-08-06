"""Docling → batch LLM → JSON merge. Reuses knowledge/policy parse + oneshot_llm."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.utils.json import parse_json_markdown

from deerflow.config.app_config import AppConfig
from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.doc_parse.contract import DocParseMeta, DocParseResponse
from deerflow.doc_parse.prompt_hints import PromptHints, extract_prompt_hints
from deerflow.models import create_chat_model
from deerflow.utils.file_conversion import (
    ParseResult,
    parse_file_bytes_with_fallback,
    parse_markitdown_bytes,
    sanitize_media,
)
from deerflow.utils.llm_text import strip_think_blocks
from deerflow.utils.oneshot_llm import run_oneshot_llm

logger = logging.getLogger(__name__)

# Batch sizing derived from model max_tokens; compact docs go in one LLM call.
_CONTEXT_TOKENS = 128_000
_PROMPT_RESERVE_TOKENS = 2048
_CHARS_PER_TOKEN = 2
_MAX_CONCURRENT = 8
# Single-shot only for very small documents; larger docs use a few medium batches.
_COMPACT_DOC_CHARS = 8_000
_COMPACT_DOC_BLOCKS = 12

_ATX_HEADING_RE = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)
_BOLD_HEADING_RE = re.compile(
    r"(?=^\*\*[^*\n]{1,80}\*\*(?:[\s\u3000]|$))",
    re.MULTILINE,
)


class DocParseError(Exception):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ParseBatchLimits:
    max_chars: int
    max_blocks: int | None
    max_concurrent: int


def resolve_parse_batch_limits(*, app_config: AppConfig, model_name: str | None = None) -> ParseBatchLimits:
    slot = (model_name or "default").strip() or "default"
    model = app_config.get_model_config(slot) or app_config.get_model_config("default")
    if model is None:
        raise DocParseError("no model configured for document parse")

    raw_max_tokens = getattr(model, "max_tokens", None)
    if raw_max_tokens is None and hasattr(model, "model_dump"):
        raw_max_tokens = model.model_dump().get("max_tokens")
    if not raw_max_tokens:
        raise DocParseError(f"model {model.name!r} missing max_tokens; required for parse batch sizing")

    max_tokens = int(raw_max_tokens)
    input_tokens = _CONTEXT_TOKENS - _PROMPT_RESERVE_TOKENS - max_tokens
    if input_tokens < 4096:
        input_tokens = 4096
    max_chars = input_tokens * _CHARS_PER_TOKEN
    max_blocks = min(20, max(12, max_tokens // 1365))
    return ParseBatchLimits(max_chars=max_chars, max_blocks=max_blocks, max_concurrent=_MAX_CONCURRENT)


def _prompt_hash(prompt: str) -> str:
    return f"sha256:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"


def _to_markdown(data: bytes, filename: str) -> tuple[ParseResult, str]:
    """Return (parse result, backend name). Prefers fast paths for text and Word."""
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        text = sanitize_media(data.decode("utf-8", errors="replace"))
        if text.strip():
            return ParseResult(text=text, parse_quality="ok"), "text"
    if suffix in {".doc", ".docx"}:
        parsed = parse_markitdown_bytes(data, filename)
        if parsed.parse_quality == "ok" and (parsed.text or "").strip():
            return parsed, "markitdown"
    return parse_file_bytes_with_fallback(data, filename)


def _parse_json(raw: str) -> Any:
    text = strip_think_blocks(raw)
    if not text.strip():
        raise DocParseError("model returned empty response")
    try:
        return parse_json_markdown(text)
    except Exception as exc:
        raise DocParseError(f"failed to parse model output as JSON: {exc}") from exc


def _merge(left: Any, right: Any) -> Any:
    if isinstance(left, list) and isinstance(right, list):
        return left + left.__class__(right)
    if isinstance(left, dict) and isinstance(right, dict):
        out = dict(left)
        for key, value in right.items():
            out[key] = _merge(out[key], value) if key in out else value
        return out
    if left in (None, "", [], {}):
        return right
    return left


def _merge_all(batches: list[Any]) -> Any:
    if not batches:
        return {}
    merged = batches[0]
    for batch in batches[1:]:
        merged = _merge(merged, batch)
    return merged


def _split_by_pattern(text: str, pattern: re.Pattern[str]) -> list[str]:
    parts = [part.strip() for part in pattern.split(text.strip()) if part.strip()]
    return parts if len(parts) > 1 else [text.strip()]


def _split_by_prompt_patterns(text: str, hints: PromptHints) -> list[str]:
    for pattern in hints.split_patterns:
        parts = _split_by_pattern(text, pattern)
        if len(parts) > 1:
            return parts
    return [text.strip()]


def _split_by_headings(text: str) -> list[str]:
    for pattern in (_ATX_HEADING_RE, _BOLD_HEADING_RE):
        parts = _split_by_pattern(text, pattern)
        if len(parts) > 1:
            return parts
    return [text.strip()]


def _chunk_text(text: str, *, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split_at = text.rfind("\n\n", start, end)
            if split_at > start:
                end = split_at + 2
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end <= start:
            end = min(start + max_chars, len(text))
        start = end
    return chunks


def _markdown_blocks(text: str, *, hints: PromptHints | None = None) -> list[str]:
    text = text.strip()
    if not text:
        return []

    hints = hints or PromptHints()
    if hints.split_patterns:
        parts = _split_by_prompt_patterns(text, hints)
        if len(parts) > 1:
            return parts

    parts = _split_by_headings(text)
    if len(parts) > 1:
        return parts
    return [text]


def _batches(
    blocks: list[str],
    *,
    max_chars: int,
    max_blocks: int | None = None,
) -> list[str]:
    if not blocks:
        return []

    joined = "\n\n".join(blocks)
    total_chars = len(joined)
    block_count = len(blocks)
    if total_chars <= min(max_chars, _COMPACT_DOC_CHARS) and block_count <= _COMPACT_DOC_BLOCKS:
        return [joined]
    if total_chars <= max_chars and (max_blocks is None or block_count <= max_blocks):
        return [joined]

    out: list[str] = []
    buf: list[str] = []
    size = 0
    for block in blocks:
        if len(block) > max_chars:
            if buf:
                out.append("\n\n".join(buf))
                buf, size = [], 0
            out.extend(_chunk_text(block, max_chars=max_chars))
            continue
        need = len(block) + (2 if buf else 0)
        block_cap_reached = max_blocks is not None and len(buf) >= max_blocks
        if buf and (size + need > max_chars or block_cap_reached):
            out.append("\n\n".join(buf))
            buf, size = [block], len(block)
        else:
            buf.append(block)
            size += need
    if buf:
        out.append("\n\n".join(buf))
    return out


def _normalize_grounding_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text.strip())
    return re.sub(r"\s+", " ", normalized)


def _body_grounded_in_source(body: str, source: str) -> bool:
    norm_body = _normalize_grounding_text(body)
    if not norm_body:
        return True
    norm_source = _normalize_grounding_text(source)
    if norm_body in norm_source:
        return True
    if len(norm_body) >= 12:
        prefix = norm_body[: max(12, len(norm_body) // 2)]
        if prefix in norm_source:
            return True
    return False


def _new_row_no() -> str:
    return str(uuid.uuid4())


def _row_no_is_preserved(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    row_id = value.strip()
    if not row_id or row_id.isdigit():
        return False
    return True


def _attach_row_no(data: Any) -> None:
    if not isinstance(data, dict):
        return
    details = data.get("details")
    if not isinstance(details, list):
        return
    seen: set[str] = set()
    for item in details:
        if not isinstance(item, dict):
            continue
        existing = item.get("row_no")
        if _row_no_is_preserved(existing):
            seen.add(str(existing).strip())
            continue
        while True:
            row_id = _new_row_no()
            if row_id not in seen:
                break
        item["row_no"] = row_id
        seen.add(row_id)


def _collect_warnings(data: Any, *, source_text: str = "") -> list[str]:
    warnings: list[str] = []
    if not isinstance(data, dict):
        return warnings
    details = data.get("details")
    if not isinstance(details, list):
        return warnings
    if not details:
        warnings.append("details[] is empty after merge")
        return warnings

    norm_source = _normalize_grounding_text(source_text) if source_text.strip() else ""
    labels: list[str] = []
    for index, item in enumerate(details):
        if not isinstance(item, dict):
            warnings.append(f"details[{index}] is not an object")
            continue
        body = item.get("body")
        label = item.get("segment_label") or item.get("label") or index
        if body is None or not str(body).strip():
            warnings.append(f"details[{index}] ({label!r}) has empty body")
        elif norm_source and not _body_grounded_in_source(str(body), source_text):
            warnings.append(f"details[{index}] ({label!r}) body not found in source (possible paraphrase)")
        label = item.get("segment_label") or item.get("label")
        if isinstance(label, str) and label.strip():
            labels.append(label.strip())

    seen: set[str] = set()
    for label in labels:
        if label in seen:
            warnings.append(f"duplicate segment_label: {label!r}")
        seen.add(label)
    return warnings


def _validate_schema(data: Any, schema: dict[str, Any]) -> None:
    import jsonschema

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise DocParseError(f"output_schema validation failed: {exc.message}") from exc


def _batch_user_content(*, chunk: str, index: int, total: int) -> str:
    return (
        f"Document batch {index + 1}/{total}.\n"
        "Return only JSON per the system instructions (segment_prompt).\n"
        "Process every segment/clause present in this chunk; do not skip, invent, or paraphrase.\n"
        'If this chunk has no extractable segments, return {"details":[]} (keep other fields empty).\n\n'
        f"<document_chunk>\n{chunk}\n</document_chunk>"
    )


async def _run_batch_llm(
    *,
    index: int,
    chunk: str,
    total: int,
    prompt: str,
    app_config: AppConfig,
    chat_model: BaseChatModel,
    semaphore: asyncio.Semaphore,
) -> Any:
    async with semaphore:
        try:
            raw = await run_oneshot_llm(
                system_instruction=prompt,
                user_content=_batch_user_content(chunk=chunk, index=index, total=total),
                run_name="doc_parse",
                app_config=app_config,
                model=chat_model,
            )
        except Exception as exc:
            logger.exception("doc_parse LLM failed batch=%s/%s", index + 1, total)
            raise DocParseError(f"model call failed: {exc}", status_code=503) from exc
        return _parse_json(raw)


async def parse_document(
    *,
    data: bytes,
    filename: str,
    segment_prompt: str,
    output_schema: dict[str, Any] | None = None,
    app_config: AppConfig,
    model_name: str | None = None,
) -> DocParseResponse:
    parse_cfg = get_knowledge_config().parse
    timeout = parse_cfg.timeout_seconds
    started = time.perf_counter()
    try:
        if timeout and timeout > 0:
            return await asyncio.wait_for(
                _parse_document_body(
                    data=data,
                    filename=filename,
                    segment_prompt=segment_prompt,
                    output_schema=output_schema,
                    app_config=app_config,
                    model_name=model_name,
                    started=started,
                ),
                timeout=timeout,
            )
        return await _parse_document_body(
            data=data,
            filename=filename,
            segment_prompt=segment_prompt,
            output_schema=output_schema,
            app_config=app_config,
            model_name=model_name,
            started=started,
        )
    except TimeoutError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        raise DocParseError(
            f"document parse timed out after {timeout}s ({elapsed}ms elapsed)",
            status_code=504,
        ) from exc


async def _parse_document_body(
    *,
    data: bytes,
    filename: str,
    segment_prompt: str,
    output_schema: dict[str, Any] | None,
    app_config: AppConfig,
    model_name: str | None,
    started: float,
) -> DocParseResponse:
    prompt = segment_prompt.strip()
    if not prompt:
        raise DocParseError("segment_prompt is required")

    hints = extract_prompt_hints(prompt)
    source_filename = Path(filename).name or "document.bin"
    t0 = time.perf_counter()
    parsed, parse_backend = await asyncio.to_thread(_to_markdown, data, source_filename)
    t_parse = time.perf_counter()
    source_text = parsed.text or ""
    if parsed.parse_quality == "failed" or not source_text.strip():
        raise DocParseError(parsed.error or "document parse failed")

    blocks = await asyncio.to_thread(_markdown_blocks, source_text, hints=hints)
    batch_limits = resolve_parse_batch_limits(app_config=app_config, model_name=model_name)
    batches = _batches(blocks, max_chars=batch_limits.max_chars, max_blocks=batch_limits.max_blocks)
    t_blocks = time.perf_counter()
    if not batches:
        raise DocParseError("document produced no text blocks")

    total = len(batches)
    chat_model = create_chat_model(name=model_name, thinking_enabled=False, app_config=app_config)
    semaphore = asyncio.Semaphore(batch_limits.max_concurrent)
    batch_results = await asyncio.gather(
        *[
            _run_batch_llm(
                index=index,
                chunk=chunk,
                total=total,
                prompt=prompt,
                app_config=app_config,
                chat_model=chat_model,
                semaphore=semaphore,
            )
            for index, chunk in enumerate(batches)
        ]
    )
    t_llm = time.perf_counter()

    merged = _merge_all(list(batch_results))
    if output_schema:
        _validate_schema(merged, output_schema)
    _attach_row_no(merged)
    warnings = _collect_warnings(merged, source_text=source_text)
    if warnings:
        logger.info("doc_parse quality warnings for %s: %s", source_filename, warnings)

    parse_ms = int((t_parse - t0) * 1000)
    block_ms = int((t_blocks - t_parse) * 1000)
    llm_ms = int((t_llm - t_blocks) * 1000)
    total_ms = int((t_llm - started) * 1000)
    logger.info(
        "doc_parse %s: backend=%s blocks=%s batches=%s parse_ms=%s block_ms=%s llm_ms=%s total_ms=%s",
        source_filename,
        parse_backend,
        len(blocks),
        total,
        parse_ms,
        block_ms,
        llm_ms,
        total_ms,
    )

    return DocParseResponse(
        data=merged,
        meta=DocParseMeta(
            source_filename=source_filename,
            segment_prompt_hash=_prompt_hash(prompt),
            block_count=len(blocks),
            batch_count=total,
            parse_quality=parsed.parse_quality,
            parse_backend=parse_backend,
            warnings=warnings,
            parse_ms=parse_ms,
            block_ms=block_ms,
            llm_ms=llm_ms,
            total_ms=total_ms,
        ),
    )
