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

# Batch sizing: input from context_window; batch count mainly capped by max_tokens (JSON output).
_DEFAULT_CONTEXT_WINDOW = 128_000
_PROMPT_OVERHEAD_TOKENS = 2048
_CHARS_PER_TOKEN = 2
_TOKENS_PER_DETAIL_EST = 400

_markdown_node_parser: Any | None = None

_ATX_HEADING_RE = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)
# MarkItDown / Word: **Heading** at line start (optionally followed by content on the same line).
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


def _resolve_parse_model_name(*, app_config: AppConfig, model_name: str | None) -> str:
    configured = (model_name or get_knowledge_config().parse.model_name or "").strip()
    if configured:
        return configured
    models = getattr(app_config, "models", None)
    if models:
        first = models[0]
        return getattr(first, "name", str(first))
    return "default"


def _int_from_model_config(model_cfg: Any, key: str) -> int | None:
    raw = getattr(model_cfg, key, None)
    if isinstance(raw, int) and raw > 0:
        return raw
    extra = getattr(model_cfg, "model_extra", None) or getattr(model_cfg, "__pydantic_extra__", None)
    if isinstance(extra, dict):
        raw = extra.get(key)
        if isinstance(raw, int) and raw > 0:
            return raw
    if hasattr(model_cfg, "model_dump"):
        raw = model_cfg.model_dump(exclude_none=True).get(key)
        if isinstance(raw, int) and raw > 0:
            return raw
    return None


def _max_tokens_from_model_config(model_cfg: Any) -> int | None:
    return _int_from_model_config(model_cfg, "max_tokens")


def _context_window_from_model_config(model_cfg: Any) -> int | None:
    return _int_from_model_config(model_cfg, "context_window")


def _model_config_for_parse(*, app_config: AppConfig, model_name: str) -> Any | None:
    get_model_config = getattr(app_config, "get_model_config", None)
    if callable(get_model_config):
        model_cfg = get_model_config(model_name)
        if model_cfg is not None:
            return model_cfg
    for model in getattr(app_config, "models", None) or []:
        if getattr(model, "name", None) == model_name:
            return model
    return None


def _model_max_tokens(*, app_config: AppConfig, model_name: str) -> int:
    model_cfg = _model_config_for_parse(app_config=app_config, model_name=model_name)
    if model_cfg is not None:
        found = _max_tokens_from_model_config(model_cfg)
        if found is not None:
            return found

    for model in getattr(app_config, "models", None) or []:
        found = _max_tokens_from_model_config(model)
        if found is not None:
            logger.warning(
                "doc_parse: max_tokens missing for model %r; using %r (%s)",
                model_name,
                getattr(model, "name", model),
                found,
            )
            return found

    raise DocParseError(
        f"cannot resolve max_tokens for parse model {model_name!r}; set max_tokens on config.models[]",
        status_code=422,
    )


def resolve_parse_batch_limits(*, app_config: AppConfig, model_name: str | None = None) -> ParseBatchLimits:
    """Input budget from context_window; batch count mainly from max_tokens (JSON output size)."""
    resolved_model = _resolve_parse_model_name(app_config=app_config, model_name=model_name)
    model_cfg = _model_config_for_parse(app_config=app_config, model_name=resolved_model)
    max_tokens = _model_max_tokens(app_config=app_config, model_name=resolved_model)
    context_window = (_context_window_from_model_config(model_cfg) if model_cfg is not None else None) or _DEFAULT_CONTEXT_WINDOW
    input_tokens = max(context_window - _PROMPT_OVERHEAD_TOKENS - max_tokens, 4096)
    max_chars = input_tokens * _CHARS_PER_TOKEN
    max_blocks = max(max_tokens // _TOKENS_PER_DETAIL_EST, 1)
    return ParseBatchLimits(
        max_chars=max_chars,
        max_blocks=max_blocks,
        max_concurrent=8,
    )


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
        return left + right
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
    """Generic heading split: ATX # lines, then MarkItDown **bold** line-start headings."""
    for pattern in (_ATX_HEADING_RE, _BOLD_HEADING_RE):
        parts = _split_by_pattern(text, pattern)
        if len(parts) > 1:
            return parts
    return [text.strip()]


def _get_markdown_node_parser() -> Any:
    global _markdown_node_parser
    if _markdown_node_parser is None:
        from llama_index.core.node_parser import MarkdownNodeParser

        _markdown_node_parser = MarkdownNodeParser()
    return _markdown_node_parser


def _markdown_blocks_from_parser(text: str) -> list[str]:
    from llama_index.core import Document

    nodes = _get_markdown_node_parser().get_nodes_from_documents([Document(text=text)])
    blocks: list[str] = []
    for node in nodes:
        body = (node.get_content() if hasattr(node, "get_content") else getattr(node, "text", "")) or ""
        body = str(body).strip()
        if body:
            blocks.append(body)
    return blocks or [text]


def _chunk_text(text: str, *, max_chars: int) -> list[str]:
    """Split an oversized block by size, preferring paragraph boundaries."""
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
    """Split markdown into sections (patterns from segment_prompt when available)."""
    text = text.strip()
    if not text:
        return []

    hints = hints or PromptHints()

    try:
        blocks = _markdown_blocks_from_parser(text)
    except Exception as exc:
        logger.warning("MarkdownNodeParser failed; using whole document: %s", exc)
        blocks = [text]

    if len(blocks) == 1:
        heading_blocks = _split_by_headings(blocks[0])
        if len(heading_blocks) > 1:
            blocks = heading_blocks
        elif hints.split_patterns:
            label_blocks = _split_by_prompt_patterns(blocks[0], hints)
            if len(label_blocks) > 1:
                blocks = label_blocks

    return blocks


def _batches(
    blocks: list[str],
    *,
    max_chars: int,
    max_blocks: int | None = None,
) -> list[str]:
    """Pack sections into LLM batches; limit by character budget and section count."""
    if not blocks:
        return []

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
    """Collapse whitespace and unify compatibility forms for grounding checks."""
    normalized = unicodedata.normalize("NFKC", text.strip())
    return re.sub(r"\s+", " ", normalized)


def _body_grounded_in_source(body: str, source: str) -> bool:
    """True when ``body`` (or a long enough prefix) appears in ``source`` after normalization."""
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


def _match_candidates(body: str) -> list[str]:
    """Search strings for locating ``body`` in source markdown (longest first)."""
    raw = str(body).strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        v = value.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    add(raw)
    first_line = raw.split("\n")[0].strip()
    if first_line != raw:
        add(first_line)
    first_para = raw.split("\n\n")[0].strip()
    if first_para != raw and first_para != first_line:
        add(first_para)
    norm_body = _normalize_grounding_text(raw)
    add(norm_body)
    if len(norm_body) >= 12:
        add(norm_body[: max(12, len(norm_body) // 2)])
    return out


def _row_no_at(source_text: str, index: int) -> int:
    return source_text[:index].count("\n") + 1


def _find_row_no(body: str, source_text: str, *, after_line: int = 0) -> int | None:
    """1-based line number in ``source_text`` where ``body`` best matches after ``after_line``."""
    if not str(body).strip() or not source_text.strip():
        return None

    candidates = _match_candidates(body)
    lines = source_text.splitlines()

    for index, line in enumerate(lines, start=1):
        if index <= after_line:
            continue
        norm_line = _normalize_grounding_text(line)
        for cand in candidates:
            if cand in line or cand in norm_line:
                return index

    for cand in candidates:
        start = 0
        while True:
            idx = source_text.find(cand, start)
            if idx < 0:
                break
            line = _row_no_at(source_text, idx)
            if line > after_line:
                return line
            start = idx + 1

    norm_source = _normalize_grounding_text(source_text)
    for cand in candidates:
        pos = 0
        while True:
            pos = norm_source.find(cand, pos)
            if pos < 0:
                break
            consumed = 0
            for index, line in enumerate(lines, start=1):
                consumed += len(_normalize_grounding_text(line))
                if consumed >= pos and index > after_line:
                    return index
            pos += 1
    return None


def _new_row_no() -> str:
    """UUID string for a detail row; stable across knowledge import."""
    return str(uuid.uuid4())


def _row_no_is_preserved(value: Any) -> bool:
    """Keep caller-provided string ids; reject legacy numeric line numbers."""
    if not isinstance(value, str):
        return False
    row_id = value.strip()
    if not row_id:
        return False
    if row_id.isdigit():
        return False
    return True


def _attach_row_no(data: Any, *, source_text: str = "") -> None:
    """Assign a unique UUID ``row_no`` to each ``details[]`` item.

    Caller/LLM may pre-set ``row_no`` as a non-empty string (e.g. business id);
    those values are kept. Missing or numeric legacy values are replaced with a new id.
    ``source_text`` is accepted for call-site compatibility but is not used for row ids.
    """
    _ = source_text
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


def _detail_label(item: dict[str, Any], hints: PromptHints) -> str:
    for key in (hints.label_field, "segment_label", "label"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_chapter_paths(data: dict[str, Any], *, hints: PromptHints) -> None:
    """Fill chapter_path from the nearest preceding chapter heading when LLM reused a label."""
    if hints.chapter_pattern is None and hints.label_pattern is None:
        return
    details = data.get("details")
    if not isinstance(details, list):
        return
    current_chapter = ""
    for item in details:
        if not isinstance(item, dict):
            continue
        chapter = str(item.get(hints.chapter_field) or item.get("chapter_path") or "").strip()
        label = _detail_label(item, hints)
        if chapter and hints.looks_like_chapter(chapter, label=label):
            current_chapter = chapter
            continue
        if current_chapter and (not chapter or chapter == label or hints.matches_label(chapter)):
            item[hints.chapter_field] = current_chapter
            if hints.chapter_field != "chapter_path" and "chapter_path" in item:
                item["chapter_path"] = current_chapter


def _next_label_boundary(tail: str, *, label: str, hints: PromptHints, known_labels: list[str]) -> int | None:
    positions: list[int] = []
    for candidate in known_labels:
        if candidate != label:
            idx = tail.find(candidate)
            if idx > 0:
                positions.append(idx)
    if hints.label_pattern is not None:
        for match in hints.label_pattern.finditer(tail):
            if match.start() > 0:
                positions.append(match.start())
    return min(positions) if positions else None


def _repair_body_from_source(
    *,
    label: str,
    body: str,
    source_text: str,
    hints: PromptHints,
    known_labels: list[str] | None = None,
) -> str | None:
    """Recover verbatim body text from source when the model paraphrased."""
    if _body_grounded_in_source(body, source_text):
        return body
    label = label.strip()
    if not label:
        return None
    labels = known_labels or []
    pos = 0
    while True:
        idx = source_text.find(label, pos)
        if idx < 0:
            return None
        start = idx + len(label)
        tail = re.sub(r"^[\s\u3000：:、，,。.；;（(]+", "", source_text[start:])
        if not tail:
            pos = idx + 1
            continue
        boundary = _next_label_boundary(tail, label=label, hints=hints, known_labels=labels)
        if boundary is not None and boundary == 0:
            pos = idx + 1
            continue
        extracted = tail[:boundary].strip() if boundary is not None else tail.strip()
        if extracted and _body_grounded_in_source(extracted, source_text):
            return extracted
        pos = idx + 1


def _repair_details_from_source(data: dict[str, Any], *, source_text: str, hints: PromptHints) -> None:
    details = data.get("details")
    if not isinstance(details, list) or not source_text.strip():
        return
    if hints.label_pattern is None:
        return
    known_labels = [_detail_label(item, hints) for item in details if isinstance(item, dict)]
    known_labels = [value for value in known_labels if value]
    for item in details:
        if not isinstance(item, dict):
            continue
        body = str(item.get(hints.body_field) or item.get("body") or "")
        label = _detail_label(item, hints)
        repaired = _repair_body_from_source(
            label=label,
            body=body,
            source_text=source_text,
            hints=hints,
            known_labels=known_labels,
        )
        if repaired is not None:
            key = hints.body_field if hints.body_field in item else "body"
            item[key] = repaired


def _collect_warnings(data: Any, *, source_text: str = "") -> list[str]:
    """Lightweight post-merge checks; does not enforce business schema."""
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

    blocks = _markdown_blocks(source_text, hints=hints)
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
    if isinstance(merged, dict):
        _normalize_chapter_paths(merged, hints=hints)
        _repair_details_from_source(merged, source_text=source_text, hints=hints)
    _attach_row_no(merged, source_text=source_text)

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
