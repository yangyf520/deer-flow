"""Docling → batch LLM → JSON merge. Reuses knowledge/policy parse + oneshot_llm."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.utils.json import parse_json_markdown

from deerflow.config.app_config import AppConfig
from deerflow.doc_parse.contract import DocParseMeta, DocParseResponse
from deerflow.utils.file_conversion import ParseResult, parse_file_bytes
from deerflow.utils.llm_text import strip_think_blocks
from deerflow.utils.oneshot_llm import run_oneshot_llm

logger = logging.getLogger(__name__)

# Keep each LLM call small enough for output JSON (Map-Reduce batches).
MAX_BATCH_CHARS = 4000
MAX_BLOCKS_PER_BATCH = 10
MAX_CONCURRENT_BATCHES = 4
_BOLD_LABEL_MAX_LEN = 80
_GROUNDING_MIN_BODY_LEN = 12

_ATX_HEADING_RE = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)
# MarkItDown / Word: **Heading** at line start (optionally followed by content on the same line).
_BOLD_HEADING_RE = re.compile(
    rf"(?=^\*\*[^*\n]{{1,{_BOLD_LABEL_MAX_LEN}}}\*\*(?:[\s\u3000]|$))",
    re.MULTILINE,
)


class DocParseError(Exception):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _prompt_hash(prompt: str) -> str:
    return f"sha256:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"


def _markitdown_bytes(data: bytes, filename: str) -> ParseResult:
    """Reuse upload-sidecar MarkItDown when Docling is unavailable (e.g. missing torch)."""
    import tempfile

    try:
        from markitdown import MarkItDown
    except ImportError:
        return ParseResult(text="", parse_quality="failed", error="MarkItDown is not installed")

    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = Path(tmp.name)
    try:
        text = (MarkItDown().convert(str(path)).text_content or "").strip()
        if not text:
            return ParseResult(text="", parse_quality="failed", error="empty MarkItDown output")
        return ParseResult(text=text, parse_quality="ok")
    except Exception as exc:
        logger.warning("MarkItDown fallback failed for %s: %s", filename, exc)
        return ParseResult(text="", parse_quality="failed", error=str(exc))
    finally:
        path.unlink(missing_ok=True)


def _to_markdown(data: bytes, filename: str) -> tuple[ParseResult, str]:
    """Return (parse result, backend name: ``docling`` | ``markitdown``)."""
    parsed = parse_file_bytes(data, filename)
    if parsed.parse_quality == "ok" and (parsed.text or "").strip():
        return parsed, "docling"
    logger.info("Docling unavailable for %s (%s); falling back to MarkItDown", filename, parsed.error)
    return _markitdown_bytes(data, filename), "markitdown"


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
    max_chars: int = MAX_BATCH_CHARS,
    max_blocks: int = MAX_BLOCKS_PER_BATCH,
) -> list[str]:
    """Pack sections into LLM batches; limit count and chars so output JSON stays bounded."""
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
        if buf and (size + need > max_chars or len(buf) >= max_blocks):
            out.append("\n\n".join(buf))
            buf, size = [block], len(block)
        else:
            buf.append(block)
            size += need
    if buf:
        out.append("\n\n".join(buf))
    return out


def _normalize_grounding_text(text: str) -> str:
    """Collapse whitespace for substring grounding checks."""
    return re.sub(r"\s+", " ", text.strip())


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
    model_name: str | None,
    semaphore: asyncio.Semaphore,
) -> Any:
    async with semaphore:
        try:
            raw = await run_oneshot_llm(
                system_instruction=prompt,
                user_content=_batch_user_content(chunk=chunk, index=index, total=total),
                run_name="doc_parse",
                app_config=app_config,
                model_name=model_name,
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
    batches = _batches(blocks)
    if not batches:
        raise DocParseError("document produced no text blocks")

    total = len(batches)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)
    batch_results = await asyncio.gather(
        *[
            _run_batch_llm(
                index=index,
                chunk=chunk,
                total=total,
                prompt=prompt,
                app_config=app_config,
                model_name=model_name,
                semaphore=semaphore,
            )
            for index, chunk in enumerate(batches)
        ]
    )

    merged = _merge_all(list(batch_results))
    if output_schema:
        _validate_schema(merged, output_schema)

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
