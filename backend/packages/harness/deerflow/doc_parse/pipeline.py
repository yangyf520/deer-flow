"""Docling → batch LLM → JSON merge. Reuses knowledge/policy parse + oneshot_llm."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
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

# Batch sizing: derived from config.models[*].max_tokens at runtime (no knowledge.parse knobs).
_DEFAULT_MAX_BLOCKS_PER_BATCH = 20
_DEFAULT_MAX_CONCURRENT_BATCHES = 8
_INPUT_CHARS_PER_TOKEN = 2
_INPUT_TOKEN_FRACTION = 0.5  # reserve the other half for JSON output
_FALLBACK_MAX_TOKENS = 8192

_BOLD_LABEL_MAX_LEN = 80
_GROUNDING_MIN_BODY_LEN = 12

_ATX_HEADING_RE = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)
# MarkItDown / Word: **Heading** at line start (optionally followed by content on the same line).
_BOLD_HEADING_RE = re.compile(
    rf"(?=^\*\*[^*\n]{{1,{_BOLD_LABEL_MAX_LEN}}}\*\*(?:[\s\u3000]|$))",
    re.MULTILINE,
)
_ARTICLE_LABEL_RE = re.compile(r"^第[0-9一二三四五六七八九十百千]+条$")
_CHAPTER_HEADING_RE = re.compile(r"第[0-9一二三四五六七八九十百千]+章")
_ARTICLE_MARKER_RE = re.compile(r"第[0-9一二三四五六七八九十百千]+条")
_ENGLISH_CHAPTER_RE = re.compile(r"(?:Chapter|Part|Section)\s+\d", re.IGNORECASE)


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


def _model_max_tokens(*, app_config: AppConfig, model_name: str) -> int:
    get_model_config = getattr(app_config, "get_model_config", None)
    model_cfg = get_model_config(model_name) if callable(get_model_config) else None
    if model_cfg is not None:
        raw = model_cfg.model_dump(exclude_none=True).get("max_tokens")
        if isinstance(raw, int) and raw > 0:
            return raw
    return _FALLBACK_MAX_TOKENS


def resolve_parse_batch_limits(*, app_config: AppConfig, model_name: str | None = None) -> ParseBatchLimits:
    """Batch sizing from the parse model's max_tokens (config.models slot)."""
    resolved_model = _resolve_parse_model_name(app_config=app_config, model_name=model_name)
    max_tokens = _model_max_tokens(app_config=app_config, model_name=resolved_model)
    max_chars = max(int(max_tokens * _INPUT_CHARS_PER_TOKEN * _INPUT_TOKEN_FRACTION), 256)
    return ParseBatchLimits(
        max_chars=max_chars,
        max_blocks=_DEFAULT_MAX_BLOCKS_PER_BATCH,
        max_concurrent=_DEFAULT_MAX_CONCURRENT_BATCHES,
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


def _split_by_headings(text: str) -> list[str]:
    """Generic heading split: ATX # lines, then MarkItDown **bold** line-start headings."""
    for pattern in (_ATX_HEADING_RE, _BOLD_HEADING_RE):
        parts = _split_by_pattern(text, pattern)
        if len(parts) > 1:
            return parts
    return [text.strip()]


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


def _markdown_blocks(text: str) -> list[str]:
    """Split markdown into sections (generic — no domain-specific rules)."""
    text = text.strip()
    if not text:
        return []
    try:
        from llama_index.core import Document
        from llama_index.core.node_parser import MarkdownNodeParser

        nodes = MarkdownNodeParser().get_nodes_from_documents([Document(text=text)])
        blocks = []
        for node in nodes:
            body = (node.get_content() if hasattr(node, "get_content") else getattr(node, "text", "")) or ""
            body = str(body).strip()
            if body:
                blocks.append(body)
        blocks = blocks or [text]
    except Exception as exc:
        logger.warning("MarkdownNodeParser failed; using whole document: %s", exc)
        blocks = [text]

    if len(blocks) == 1:
        heading_blocks = _split_by_headings(blocks[0])
        if len(heading_blocks) > 1:
            blocks = heading_blocks
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
    if len(norm_body) >= _GROUNDING_MIN_BODY_LEN:
        prefix = norm_body[: max(_GROUNDING_MIN_BODY_LEN, len(norm_body) // 2)]
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
    if len(norm_body) >= _GROUNDING_MIN_BODY_LEN:
        add(norm_body[: max(_GROUNDING_MIN_BODY_LEN, len(norm_body) // 2)])
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


def _is_article_label(text: str) -> bool:
    return bool(_ARTICLE_LABEL_RE.match(text.strip()))


def _looks_like_chapter_path(text: str) -> bool:
    chapter = text.strip()
    if not chapter or _is_article_label(chapter):
        return False
    if _CHAPTER_HEADING_RE.search(chapter):
        return True
    return _ENGLISH_CHAPTER_RE.search(chapter) is not None


def _normalize_chapter_paths(data: dict[str, Any]) -> None:
    """Fill chapter_path from the nearest preceding chapter heading when LLM reused a label."""
    details = data.get("details")
    if not isinstance(details, list):
        return
    current_chapter = ""
    for item in details:
        if not isinstance(item, dict):
            continue
        chapter = str(item.get("chapter_path") or "").strip()
        label = str(item.get("segment_label") or item.get("label") or "").strip()
        if chapter and _looks_like_chapter_path(chapter) and chapter != label:
            current_chapter = chapter
            continue
        if current_chapter and (not chapter or chapter == label or _is_article_label(chapter)):
            item["chapter_path"] = current_chapter


def _repair_body_from_source(*, label: str, body: str, source_text: str) -> str | None:
    """Recover verbatim body text from source when the model paraphrased."""
    if _body_grounded_in_source(body, source_text):
        return body
    label = label.strip()
    if not label:
        return None
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
        next_article = _ARTICLE_MARKER_RE.search(tail)
        if next_article is not None:
            if next_article.start() == 0:
                pos = idx + 1
                continue
            extracted = tail[: next_article.start()].strip()
        else:
            extracted = tail.strip()
        if extracted and _body_grounded_in_source(extracted, source_text):
            return extracted
        pos = idx + 1


def _repair_details_from_source(data: dict[str, Any], *, source_text: str) -> None:
    details = data.get("details")
    if not isinstance(details, list) or not source_text.strip():
        return
    for item in details:
        if not isinstance(item, dict):
            continue
        body = str(item.get("body") or "")
        label = str(item.get("segment_label") or item.get("label") or "")
        repaired = _repair_body_from_source(label=label, body=body, source_text=source_text)
        if repaired is not None:
            item["body"] = repaired


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
    prompt = segment_prompt.strip()
    if not prompt:
        raise DocParseError("segment_prompt is required")

    source_filename = Path(filename).name or "document.bin"
    parsed, parse_backend = await asyncio.to_thread(_to_markdown, data, source_filename)
    source_text = parsed.text or ""
    if parsed.parse_quality == "failed" or not source_text.strip():
        raise DocParseError(parsed.error or "document parse failed")

    blocks = _markdown_blocks(source_text)
    batch_limits = resolve_parse_batch_limits(app_config=app_config, model_name=model_name)
    batches = _batches(blocks, max_chars=batch_limits.max_chars, max_blocks=batch_limits.max_blocks)
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

    merged = _merge_all(list(batch_results))
    if output_schema:
        _validate_schema(merged, output_schema)
    if isinstance(merged, dict):
        _normalize_chapter_paths(merged)
        _repair_details_from_source(merged, source_text=source_text)
    _attach_row_no(merged, source_text=source_text)

    warnings = _collect_warnings(merged, source_text=source_text)
    if warnings:
        logger.info("doc_parse quality warnings for %s: %s", source_filename, warnings)

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
        ),
    )
