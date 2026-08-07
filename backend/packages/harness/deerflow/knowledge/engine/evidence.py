"""Evidence field rules, snippet formatting, and date parsing."""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.utils.file_conversion import sanitize_media

logger = logging.getLogger(__name__)

RESERVED_CHUNK_METADATA_KEYS = frozenset(
    {
        "space_id",
        "doc_id",
        "kind",
        "sensitivity",
        "release",
        "title",
        "parse_quality",
        "tags",
        "effective_from",
        "effective_to",
        "ref_doc_id",
        "document_id",
        "doc_hash",
        "_node_content",
        "excluded_embed_metadata_keys",
        "excluded_llm_metadata_keys",
    }
)

EVIDENCE_SYSTEM_METADATA_KEYS = RESERVED_CHUNK_METADATA_KEYS | frozenset(
    {
        "block",
        "heading_path",
        "parent_id",
        "page_no",
        "asset_uri",
        "scenario",
        "spaces_searched",
        "recall_path",
        "source_filename",
        "doc_title",
        "article_no",
    }
)


def parse_as_of(value: str | date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def custom_metadata_from_chunk(meta: dict[str, Any]) -> dict[str, Any]:
    """Return caller-defined fields stored on a vector chunk (excludes system keys)."""
    out: dict[str, Any] = {}
    for key, value in (meta or {}).items():
        if not key or key.startswith("_") or key in RESERVED_CHUNK_METADATA_KEYS:
            continue
        out[key] = value
    return out


def user_attrs_from_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Caller-defined fields on Evidence metadata for JSON responses (omit when empty)."""
    out: dict[str, Any] = {}
    for key, value in (meta or {}).items():
        if not key or key.startswith("_") or key in EVIDENCE_SYSTEM_METADATA_KEYS:
            continue
        out[key] = value
    return out


def merge_custom_metadata(base: dict[str, Any], custom: dict[str, Any] | None) -> dict[str, Any]:
    """Merge document/segment attrs into ingest metadata without overriding system keys."""
    out = dict(base)
    if not custom:
        return out
    for key, value in custom.items():
        if not key or key.startswith("_") or key in RESERVED_CHUNK_METADATA_KEYS:
            continue
        out[key] = value
    return out


def instantiate_class(use: str, kwargs: dict[str, Any]) -> Any:
    """Assemble a LlamaIndex (or other) class from ``package.module:Class`` + kwargs."""
    from deerflow.reflection.resolvers import resolve_class

    cls = resolve_class(use)
    clean = {k: v for k, v in kwargs.items() if v is not None and v != ""}
    try:
        return cls(**clean)
    except TypeError:
        if "model" in clean and "model_name" not in clean:
            alt = dict(clean)
            alt["model_name"] = alt.pop("model")
            try:
                return cls(**alt)
            except TypeError:
                pass
        raise


def bm25_tokenize(text: str) -> list[str]:
    """BM25 tokenizer — swap via retrieval.bm25_tokenizer (jieba | jieba_search | whitespace)."""
    mode = (get_knowledge_config().retrieval.bm25_tokenizer or "jieba").strip().lower()
    if mode in ("whitespace", "default", "split"):
        return [t.lower() for t in (text or "").split() if t.strip()]
    import jieba

    if mode in ("jieba_search", "search", "jieba"):
        return [t.lower() for t in jieba.lcut_for_search(text or "") if t.strip()]
    return [t.lower() for t in jieba.lcut(text or "") if t.strip()]


def node_text(node: Any) -> str:
    if hasattr(node, "get_content"):
        return str(node.get_content() or "")
    return str(getattr(node, "text", "") or "")


MD_TABLE_RE = re.compile(r"\|.+\|\s*\n\|[-:\s|]+\|", re.MULTILINE)
MD_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")


def annotate_block_type(text: str) -> str:
    """Infer Evidence ``block`` from content shape (table / image / text)."""
    t = text or ""
    if "[image]" in t.lower() or "data:image/" in t.lower():
        return "image"
    if MD_TABLE_RE.search(t) or (t.count("|") >= 4 and "---" in t):
        return "table"
    return "text"


def format_evidence_snippet(text: str, query: str, *, max_chars: int = 1200) -> str:
    """Evidence-friendly excerpt: sanitize media, window around query terms, hard cap."""
    cleaned = sanitize_media(text or "")
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    terms = [t for t in bm25_tokenize(query) if len(t) >= 2][:12]
    best_i = 0
    if terms:
        lower = cleaned.lower()
        hits: list[int] = []
        for term in terms:
            start = 0
            tl = term.lower()
            while True:
                i = lower.find(tl, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + max(len(tl), 1)
                if len(hits) > 40:
                    break
        if hits:
            hits.sort()
            best_i = hits[len(hits) // 2]

    half = max_chars // 2
    start = max(0, best_i - half)
    end = min(len(cleaned), start + max_chars)
    start = max(0, end - max_chars)
    excerpt = cleaned[start:end].strip()
    if start > 0:
        m = re.search(r"[\n。；;]", excerpt)
        if m and m.start() < 80:
            excerpt = excerpt[m.start() + 1 :].lstrip()
        excerpt = "…" + excerpt
    if end < len(cleaned):
        excerpt = excerpt.rstrip() + "…"
    return excerpt[: max_chars + 2]
