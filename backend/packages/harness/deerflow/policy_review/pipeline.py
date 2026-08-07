"""Policy review pipeline: prepare → retrieve → finalize."""

from __future__ import annotations

import asyncio
import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deerflow.policy_review.contract import (
    LEGAL_REVIEW_V1,
    RISK_ORDER,
    LegalReviewV1,
    max_risk,
    parse_draft,
)
from deerflow.policy_review.render import render_report
from deerflow.policy_review.validate import (
    _section_matches,
    allowed_ids_from_packs,
    iter_findings,
    repair_quotes,
    validate_review,
)

# Section title carries primary signal; body budget must cover mid-document PRD clauses.
SECTION_BODY_CHARS = 2000
DEFAULT_RETRIEVE_CONCURRENCY = 8
DEFAULT_SCENARIO = "policy-review"
DEFAULT_POLICY_REVIEW_TOP_K = 20
ANCHOR_TOP_K_PER_DOC = 5
MAX_REVIEW_SECTIONS = 16
DIGEST_ITEMS_PER_SECTION = 8
DIGEST_SNIPPET_CHARS = 200
MARKDOWN_HASH_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
MARKDOWN_BOLD_HEADING_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
SECTION_HEADING_RE = re.compile(
    r"^("
    r"[一二三四五六七八九十百]+、|"  # 一、产品背景
    r"第[一二三四五六七八九十百\d]+[章节部分]|"
    r"\d+(?:\.\d+)*[\.\、\s]|"  # 1.1 / 3.2.a
    r"§[\d\.]+"
    r")"
)
QUOTE_MIN = 8
QUOTE_MAX = 180
QUOTE_MAX_LONG = 280
QUOTE_POOL_CAP = 12
SENTENCE_SPLIT = re.compile(r"(?<=[。！？；;.!?])\s*")
SECTION_LINE_RE = re.compile(r"^(?:§[\d\.]+|[\d]+(?:\.[\d]+)*[\.\、\s])")


@dataclass
class ValidationOutcome:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── prepare ─────────────────────────────────────────────────────────────────


def resolve_policy_review_top_k(top_k: int | None) -> int:
    """Default policy-review breadth when callers omit ``top_k``."""
    if top_k is not None:
        return max(1, min(int(top_k), 50))
    try:
        from deerflow.config.knowledge_config import get_knowledge_config

        cfg_top_k = int(get_knowledge_config().retrieval.top_k or 8)
    except Exception:
        cfg_top_k = 8
    return max(DEFAULT_POLICY_REVIEW_TOP_K, cfg_top_k)


def looks_like_section_heading(title: str) -> bool:
    text = (title or "").strip()
    if not text or len(text) > 80:
        return False
    if SECTION_HEADING_RE.search(text):
        return True
    markers = ("Non-Goals", "规划", "设计", "需求", "说明", "声明", "研判", "预案", "方案")
    return len(text) <= 40 and any(marker in text for marker in markers)


def split_markdown_into_sections(text: str) -> list[dict[str, str]]:
    """Split MarkItDown-style bold headings when ``MarkdownNodeParser`` yields one blob."""
    lines = (text or "").splitlines()
    sections: list[dict[str, str]] = []
    current_title = "document"
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append({"title": current_title, "body": body})

    for line in lines:
        hash_match = MARKDOWN_HASH_HEADING_RE.match(line)
        bold_match = MARKDOWN_BOLD_HEADING_RE.match(line)
        if hash_match:
            flush()
            current_title = hash_match.group(2).strip() or current_title
            current_lines = []
            continue
        if bold_match:
            title = bold_match.group(1).strip()
            if looks_like_section_heading(title):
                flush()
                current_title = title
                current_lines = []
                continue
        current_lines.append(line)
    flush()
    return sections


def section_title(node: Any, index: int) -> str:
    """Map parser metadata headers to a stable section title."""
    metadata = getattr(node, "metadata", None) or {}
    for key in ("Header_6", "Header_5", "Header_4", "Header_3", "Header_2", "Header_1"):
        value = metadata.get(key)
        if value:
            return str(value).strip()
    path = metadata.get("header_path") or metadata.get("Header_Path")
    if path:
        return str(path).rsplit("/", 1)[-1].strip() or f"section-{index + 1}"
    return f"section-{index + 1}"


def prepare_sections(path: Path | str, *, title: str | None = None) -> dict[str, Any]:
    """Parse with Docling (MarkItDown fallback), then split Markdown via LlamaIndex MarkdownNodeParser."""
    from llama_index.core import Document
    from llama_index.core.node_parser import MarkdownNodeParser

    from deerflow.utils.file_conversion import parse_file_bytes_with_fallback

    doc_path = Path(path)
    parsed, parse_backend = parse_file_bytes_with_fallback(doc_path.read_bytes(), doc_path.name)
    if parsed.parse_quality == "failed" or not (parsed.text or "").strip():
        raise ValueError(parsed.error or f"parse failed for {doc_path.name}")

    parser = MarkdownNodeParser()
    try:
        nodes = list(parser.get_nodes_from_documents([Document(text=parsed.text)]))
    except Exception:
        nodes = []

    sections: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        body = (node.get_content() if hasattr(node, "get_content") else getattr(node, "text", "")) or ""
        body = str(body).strip()
        if body:
            sections.append(
                {
                    "id": f"section-{index + 1}",
                    "title": section_title(node, index),
                    "level": 1,
                    "body": body,
                }
            )
    if not sections:
        sections = [{"id": "section-1", "title": "document", "level": 1, "body": parsed.text.strip()}]
    elif len(sections) == 1 and len(parsed.text or "") > 1500:
        fallback = split_markdown_into_sections(parsed.text)
        if len(fallback) > 1:
            sections = [
                {
                    "id": f"section-{index + 1}",
                    "title": chunk["title"],
                    "level": 1,
                    "body": chunk["body"],
                }
                for index, chunk in enumerate(fallback)
            ]

    raw_section_count = len(sections)
    sections = merge_sections(sections)

    return {
        "source_path": str(doc_path),
        "title": title or doc_path.stem,
        "parse_quality": parsed.parse_quality,
        "parse_backend": parse_backend,
        "parse_error": parsed.error,
        "markdown_chars": len(parsed.text or ""),
        "section_count": len(sections),
        "sections_merged_from": raw_section_count if raw_section_count > len(sections) else None,
        "sections": sections,
    }


def merge_sections(
    sections: list[dict[str, Any]],
    *,
    max_sections: int = MAX_REVIEW_SECTIONS,
) -> list[dict[str, Any]]:
    """Cap review sections so retrieve stays S×lanes bounded."""
    if len(sections) <= max_sections:
        return sections

    merged: list[dict[str, Any]] = []
    total = len(sections)
    base = total // max_sections
    extra = total % max_sections
    index = 0
    for chunk_index in range(max_sections):
        size = base + (1 if chunk_index < extra else 0)
        chunk = [section for section in sections[index : index + size] if isinstance(section, dict)]
        index += size
        if not chunk:
            continue
        if len(chunk) == 1:
            merged.append(dict(chunk[0]))
            continue
        titles = [str(section.get("title") or section.get("id") or "").strip() for section in chunk]
        bodies = [str(section.get("body") or "").strip() for section in chunk if str(section.get("body") or "").strip()]
        first = chunk[0]
        merged.append(
            {
                "id": str(first.get("id") or f"section-{len(merged) + 1}"),
                "title": " / ".join(title for title in titles if title) or f"section-{len(merged) + 1}",
                "level": first.get("level", 1),
                "body": "\n\n".join(bodies),
            }
        )

    for index, section in enumerate(merged):
        section["id"] = f"section-{index + 1}"
    return merged


# ── retrieve ────────────────────────────────────────────────────────────────


def section_query(section: dict[str, Any]) -> str:
    """Build a retrieval query from a prepare section (or a prior section_result)."""
    if "query" in section:
        return str(section.get("query") or "").strip()[: SECTION_BODY_CHARS + 200]

    title = str(section.get("title") or section.get("id") or section.get("section_id") or "").strip()
    body = str(section.get("body") or section.get("text") or section.get("content") or "").strip()
    if len(body) > SECTION_BODY_CHARS:
        body = body[:SECTION_BODY_CHARS]
    return f"{title}\n{body}".strip() or title


def empty_section_pack(*, section_id: str, query: str = "") -> dict[str, Any]:
    """No-hit pack when a section cannot produce a searchable query."""
    return {
        "section_id": section_id,
        "query": (query or "")[:200],
        "hit_count": 0,
        "pack": {
            "knowledge_version": "current",
            "trace_id": "",
            "items": [],
            "answer": None,
            "metadata": {"skipped": "empty_query"},
        },
        "space_results": [],
    }


def extract_quote_candidates(body: str, *, cap: int = QUOTE_POOL_CAP) -> list[str]:
    """Stable contiguous spans from section body for evidence.quote."""
    text = (body or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in SENTENCE_SPLIT.split(text) if p and p.strip()]
    if not parts:
        parts = [text]

    out: list[str] = []
    seen: set[str] = set()

    def add(quote: str, *, require_unique: bool) -> bool:
        q = quote.strip()
        if len(q) < QUOTE_MIN or q in seen:
            return False
        if require_unique and text.count(q) != 1:
            return False
        seen.add(q)
        out.append(q)
        return len(out) >= cap

    # Prefer section-prefixed lines (e.g. §1.5 …) — common PRD anchors.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not SECTION_LINE_RE.match(stripped):
            continue
        candidate = stripped if len(stripped) <= QUOTE_MAX_LONG else stripped[:QUOTE_MAX_LONG]
        if add(candidate, require_unique=False) and len(out) >= cap:
            return out

    for part in parts:
        if len(part) <= QUOTE_MAX:
            candidate = part
        else:
            head = part[:QUOTE_MAX]
            candidate = head.rsplit("，", 1)[0] if "，" in head else head
            if len(candidate) < QUOTE_MIN:
                candidate = head
        if add(candidate, require_unique=True):
            return out

    if not out:
        for part in parts:
            candidate = part if len(part) <= QUOTE_MAX else part[:QUOTE_MAX]
            if add(candidate, require_unique=False):
                return out

    # Longer spans help when models truncate mid-sentence with ellipsis.
    if len(out) < cap:
        for part in parts:
            if len(part) <= QUOTE_MIN:
                continue
            candidate = part if len(part) <= QUOTE_MAX_LONG else part[:QUOTE_MAX_LONG]
            if add(candidate, require_unique=False) and len(out) >= cap:
                break
    return out


def build_quote_pool(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-section quote candidates the model must copy verbatim."""
    pool: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or section.get("section_id") or section.get("title") or "").strip()
        pool.append(
            {
                "section_id": sid,
                "quotes": extract_quote_candidates(str(section.get("body") or "")),
            }
        )
    return pool


def slim_quote_pool(
    pool: list[dict[str, Any]] | None,
    *,
    max_quotes: int = 6,
    max_chars: int = 200,
    section_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Compact quote_pool for model-facing payloads (full pool stays in artifact)."""
    out: list[dict[str, Any]] = []
    for entry in pool or []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("section_id") or "").strip()
        if section_ids and sid and sid not in section_ids:
            matched = any(_section_matches(sid, wanted) or _section_matches(wanted, sid) for wanted in section_ids)
            if not matched:
                continue
        quotes = entry.get("quotes")
        if not isinstance(quotes, list):
            continue
        trimmed: list[str] = []
        for quote in quotes[:max_quotes]:
            if not isinstance(quote, str):
                continue
            q = quote.strip()
            if not q:
                continue
            if len(q) > max_chars:
                q = q[:max_chars].rstrip() + "…"
            trimmed.append(q)
        if trimmed:
            out.append({"section_id": sid, "quotes": trimmed})
    return out


def trim_snippet(text: str, *, limit: int = DIGEST_SNIPPET_CHARS) -> str:
    snippet = (text or "").strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rstrip() + "…"


def _digest_evidence_entry(item: dict[str, Any], *, snippet_chars: int = DIGEST_SNIPPET_CHARS) -> dict[str, Any]:
    from deerflow.knowledge.rag import user_attrs_from_metadata

    item_id = item.get("id")
    entry: dict[str, Any] = {
        "id": str(item_id).strip(),
        "kind": item.get("kind"),
        "source": item.get("source"),
        "citable_as": item.get("citable_as"),
        "snippet": trim_snippet(
            str(item.get("snippet") or item.get("title") or ""),
            limit=snippet_chars,
        ),
    }
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    attrs = user_attrs_from_metadata(meta)
    if attrs:
        entry["attrs"] = attrs
    return entry


def build_evidence_digest(
    section_results: list[dict[str, Any]],
    packs: list[dict[str, Any]],
    *,
    per_section: int = DIGEST_ITEMS_PER_SECTION,
    snippet_chars: int = DIGEST_SNIPPET_CHARS,
) -> list[dict[str, Any]]:
    """Compact per-section evidence for the model — full packs stay in artifact."""
    digest: list[dict[str, Any]] = []
    for index, row in enumerate(section_results):
        if not isinstance(row, dict):
            continue
        pack = packs[index] if index < len(packs) and isinstance(packs[index], dict) else {}
        items = pack.get("items") if isinstance(pack.get("items"), list) else []
        evidence: list[dict[str, Any]] = []
        for item in items[:per_section]:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id.strip():
                continue
            evidence.append(_digest_evidence_entry(item, snippet_chars=snippet_chars))
        digest.append(
            {
                "section_id": row.get("section_id"),
                "hit_count": row.get("hit_count", len(items)),
                "evidence": evidence,
            }
        )
    return digest


def rebuild_retrieve_result(session: dict[str, Any]) -> dict[str, Any]:
    """Rebuild model-facing retrieve payload from a stored artifact session."""
    packs = session.get("packs") if isinstance(session.get("packs"), list) else []
    sections = [section for section in (session.get("sections") or []) if isinstance(section, dict)]
    allowed = session.get("allowed_ids") if isinstance(session.get("allowed_ids"), list) else []
    if not allowed:
        allowed = sorted(allowed_ids_from_packs(packs))
    retrieval_empty = bool(session.get("retrieval_empty")) if "retrieval_empty" in session else len(allowed) == 0
    spaces_queried = session.get("spaces_queried") if isinstance(session.get("spaces_queried"), list) else []
    if not spaces_queried:
        spaces_queried = spaces_from_packs(packs)
    quote_pool = session.get("quote_pool") if isinstance(session.get("quote_pool"), list) else build_quote_pool(sections)
    scaffold = session.get("scaffold")
    if not isinstance(scaffold, dict):
        scaffold = build_draft_scaffold(
            sections,
            allowed_ids=list(allowed),
            retrieval_empty=retrieval_empty,
            spaces_queried=spaces_queried,
        )

    section_results: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        section_id = str(section.get("id") or section.get("section_id") or f"section-{index + 1}")
        pack = packs[index] if index < len(packs) and isinstance(packs[index], dict) else {}
        items = pack.get("items") if isinstance(pack.get("items"), list) else []
        section_results.append(
            {
                "section_id": section_id,
                "query": section_query(section)[:200],
                "hit_count": len(items),
                "trace_id": pack.get("trace_id") if isinstance(pack, dict) else "",
                "knowledge_version": pack.get("knowledge_version") if isinstance(pack, dict) else "",
                "space_results": [],
            }
        )

    return {
        "packs": packs,
        "allowed_ids": list(allowed),
        "retrieval_empty": retrieval_empty,
        "section_results": section_results,
        "quote_pool": quote_pool,
        "spaces_queried": spaces_queried,
        "draft_scaffold": scaffold,
        "scenario": DEFAULT_SCENARIO,
        "evidence_digest": build_evidence_digest(section_results, packs),
        "cached": True,
    }


def spaces_from_packs(packs: list[dict[str, Any]]) -> list[str]:
    """Distinct space ids actually hit, read from Evidence Pack item metadata."""
    seen: set[str] = set()
    ordered: list[str] = []
    for pack in packs:
        items = pack.get("items") if isinstance(pack, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            meta = item.get("metadata") if isinstance(item, dict) else None
            sid = str((meta or {}).get("space_id") or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                ordered.append(sid)
    return ordered


def build_draft_scaffold(
    sections: list[dict[str, Any]],
    *,
    allowed_ids: list[str],
    retrieval_empty: bool,
    spaces_queried: list[str] | None = None,
) -> dict[str, Any]:
    """Contract-shaped draft shell so the model fills findings, not invents shape."""
    dimensions: list[dict[str, Any]] = []
    for i, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or f"section-{i + 1}").strip()
        name = str(section.get("title") or sid).strip() or sid
        dimensions.append({"id": sid, "name": name, "findings": []})
    draft: dict[str, Any] = {
        "schema_hint": LEGAL_REVIEW_V1,
        "mode": "full",
        "overall_risk": "none",
        "review_status": "pending",
        "summary": "",
        "dimensions": dimensions,
        "audit": {
            "trace_id": "",
            "knowledge_version": "",
            "spaces_queried": list(spaces_queried or []),
            "allowed_refs": list(allowed_ids),
            "pipeline_stages": ["prepare", "retrieve", "draft"],
        },
        "human_review": {"status": "not_required"},
        "validation": {"status": "pending", "errors": [], "warnings": []},
    }
    if retrieval_empty:
        draft["refusal"] = {
            "reason": "empty_retrieval",
            "detail": "No evidence retrieved; do not invent violations.",
        }
    return draft


def assemble_draft(session: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    """Merge model-owned fields onto retrieve scaffold (server owns provenance)."""
    packs = session.get("packs") if isinstance(session.get("packs"), list) else []
    allowed = session.get("allowed_ids")
    if not isinstance(allowed, list):
        allowed = sorted(allowed_ids_from_packs(packs))
    scaffold = session.get("scaffold")
    if not isinstance(scaffold, dict):
        sections = [s for s in (session.get("sections") or []) if isinstance(s, dict)]
        scaffold = build_draft_scaffold(
            sections,
            allowed_ids=list(allowed),
            retrieval_empty=bool(session.get("retrieval_empty")),
        )
    assembled = copy.deepcopy(scaffold)
    assembled["summary"] = str(draft.get("summary") if draft.get("summary") is not None else assembled.get("summary") or "")
    if isinstance(draft.get("dimensions"), list) and draft["dimensions"]:
        assembled["dimensions"] = draft["dimensions"]
    if draft.get("mode"):
        assembled["mode"] = draft["mode"]
    if draft.get("overall_risk") in RISK_ORDER:
        assembled["overall_risk"] = draft["overall_risk"]
    if isinstance(draft.get("refusal"), dict):
        assembled["refusal"] = draft["refusal"]
    audit = assembled.get("audit") if isinstance(assembled.get("audit"), dict) else {}
    assembled["audit"] = audit
    audit["allowed_refs"] = list(allowed)
    if not audit.get("spaces_queried"):
        spaces = session.get("spaces_queried")
        if not isinstance(spaces, list):
            spaces = spaces_from_packs(packs)
        audit["spaces_queried"] = [str(s) for s in spaces if str(s).strip()]
    stages = [str(s) for s in (audit.get("pipeline_stages") or []) if str(s).strip()]
    for stage in ("prepare", "retrieve", "draft"):
        if stage not in stages:
            stages.append(stage)
    audit["pipeline_stages"] = stages
    return assembled


def doc_ids_from_packs(packs: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for pack in packs:
        items = pack.get("items") if isinstance(pack, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            doc_id = meta.get("doc_id") or item.get("doc_id")
            if isinstance(doc_id, str) and doc_id.strip():
                covered.add(doc_id.strip())
    return covered


async def supplement_missing_space_documents(
    *,
    session_factory: Callable[[], Any],
    user_id: str,
    system_role: str,
    spaces: list[str] | None,
    scenario: str,
    top_k_per_doc: int,
    packs: list[dict[str, Any]],
    section_results: list[dict[str, Any]],
    sem: asyncio.Semaphore,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Ensure every ready document in bound spaces contributes at least one evidence hit."""
    from sqlalchemy import select

    from deerflow.knowledge.service import resolve_agent_knowledge_scope, search
    from deerflow.persistence.knowledge.model import KnowledgeDocumentRow

    bound_spaces, _ = resolve_agent_knowledge_scope(spaces, scenario)
    if not bound_spaces:
        return packs, section_results

    covered_doc_ids = doc_ids_from_packs(packs)
    async with session_factory() as session:
        result = await session.execute(
            select(KnowledgeDocumentRow).where(
                KnowledgeDocumentRow.space_id.in_(bound_spaces),
                KnowledgeDocumentRow.status == "ready",
            )
        )
        ready_docs = list(result.scalars().all())

    missing_docs = [doc for doc in ready_docs if doc.id not in covered_doc_ids]
    if not missing_docs:
        return packs, section_results

    async def one_doc(doc: KnowledgeDocumentRow) -> dict[str, Any]:
        query = str(doc.title or doc.source_filename or doc.id).strip()
        if not query:
            return empty_section_pack(section_id=f"anchor-{doc.id[:8]}", query="")
        async with sem:
            async with session_factory() as active_session:
                pack = await search(
                    active_session,
                    user_id=user_id,
                    system_role=system_role,
                    query=query,
                    spaces=bound_spaces,
                    top_k=top_k_per_doc,
                    scenario=scenario,
                )
        dump = pack.model_dump() if hasattr(pack, "model_dump") else dict(pack)
        items = dump.get("items") or []
        meta = dump.get("metadata") if isinstance(dump.get("metadata"), dict) else {}
        return {
            "section_id": f"anchor-{doc.id[:8]}",
            "query": query[:200],
            "hit_count": len(items),
            "pack": dump,
            "space_results": list(meta.get("space_results") or []),
        }

    extras = await asyncio.gather(*[one_doc(doc) for doc in missing_docs])
    extra_packs = [row["pack"] for row in extras if isinstance(row.get("pack"), dict)]
    return packs + extra_packs, section_results + list(extras)


async def retrieve_for_sections(
    session: Any | None = None,
    *,
    session_factory: Callable[[], Any] | None = None,
    user_id: str,
    system_role: str,
    sections: list[dict[str, Any]],
    spaces: list[str] | None = None,
    scenario: str | None = DEFAULT_SCENARIO,
    top_k: int | None = None,
    max_concurrency: int = DEFAULT_RETRIEVE_CONCURRENCY,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Parallel per-section retrieval; space + document paths merge inside knowledge.search."""
    from deerflow.knowledge.service import search

    if session is None and session_factory is None:
        raise ValueError("session or session_factory is required")
    scenario_id = scenario or DEFAULT_SCENARIO
    effective_top_k = resolve_policy_review_top_k(top_k)
    if not sections:
        empty_scaffold = build_draft_scaffold([], allowed_ids=[], retrieval_empty=True)
        return {
            "packs": [],
            "allowed_ids": [],
            "retrieval_empty": True,
            "section_results": [],
            "quote_pool": [],
            "draft_scaffold": empty_scaffold,
            "scenario": scenario_id,
            "evidence_digest": [],
        }

    # A SQLAlchemy AsyncSession cannot be used concurrently. Tool calls pass a
    # factory so every section gets its own session; direct callers with one
    # session are serialized for correctness.
    concurrency = max_concurrency if session_factory is not None else 1
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one_section(index: int, section: dict[str, Any]) -> dict[str, Any]:
        query = section_query(section)
        section_id = str(section.get("id") or section.get("section_id") or section.get("title") or f"section-{index}")
        if not query.strip():
            return empty_section_pack(section_id=section_id)

        async with sem:

            async def do_search(active_session: Any):
                return await search(
                    active_session,
                    user_id=user_id,
                    system_role=system_role,
                    query=query,
                    spaces=spaces,
                    top_k=effective_top_k,
                    scenario=scenario_id,
                    as_of_date=as_of_date,
                )

            if session_factory is not None:
                async with session_factory() as active_session:
                    pack = await do_search(active_session)
            else:
                pack = await do_search(session)
        dump = pack.model_dump() if hasattr(pack, "model_dump") else dict(pack)
        items = dump.get("items") or []
        meta = dump.get("metadata") if isinstance(dump.get("metadata"), dict) else {}
        return {
            "section_id": section_id,
            "query": query[:200],
            "hit_count": len(items),
            "pack": dump,
            "space_results": list(meta.get("space_results") or []),
        }

    section_results = await asyncio.gather(*[one_section(i, s) for i, s in enumerate(sections) if isinstance(s, dict)])
    packs = [r["pack"] for r in section_results]
    if session_factory is not None:
        packs, section_results = await supplement_missing_space_documents(
            session_factory=session_factory,
            user_id=user_id,
            system_role=system_role,
            spaces=spaces,
            scenario=scenario_id,
            top_k_per_doc=ANCHOR_TOP_K_PER_DOC,
            packs=packs,
            section_results=list(section_results),
            sem=sem,
        )
    allowed = sorted(allowed_ids_from_packs(packs))
    retrieval_empty = len(allowed) == 0
    spaces_queried = spaces_from_packs(packs)
    quote_pool = build_quote_pool([s for s in sections if isinstance(s, dict)])
    slim_section_results = [
        {
            "section_id": r["section_id"],
            "query": r["query"],
            "hit_count": r["hit_count"],
            "trace_id": (r["pack"] or {}).get("trace_id"),
            "knowledge_version": (r["pack"] or {}).get("knowledge_version"),
            "space_results": r.get("space_results") or [],
        }
        for r in section_results
    ]
    return {
        "packs": packs,
        "allowed_ids": allowed,
        "retrieval_empty": retrieval_empty,
        "section_results": slim_section_results,
        "quote_pool": quote_pool,
        "spaces_queried": spaces_queried,
        "draft_scaffold": build_draft_scaffold(
            [s for s in sections if isinstance(s, dict)],
            allowed_ids=allowed,
            retrieval_empty=retrieval_empty,
            spaces_queried=spaces_queried,
        ),
        "scenario": scenario_id,
        "evidence_digest": build_evidence_digest(slim_section_results, packs),
    }


# ── finalize ────────────────────────────────────────────────────────────────


def slug_id(raw: str, *, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_\-]+", "-", (raw or "").strip()).strip("-").lower()
    return text[:64] or fallback


def coerce_parties(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        out = [str(item).strip() for item in value if str(item).strip()]
        return out or None
    if isinstance(value, dict):
        out = [str(key).strip() for key in value if str(key).strip()]
        return out or None
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return None


def coerce_citations(finding: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept contract citations plus common model aliases (citation_id / ids)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        if isinstance(raw, dict):
            cid = raw.get("id") or raw.get("citation_id") or raw.get("evidence_id")
        else:
            cid = raw
        if not isinstance(cid, str):
            return
        cid = cid.strip()
        if not cid or cid in seen:
            return
        seen.add(cid)
        out.append({"id": cid})

    cites = finding.get("citations")
    if isinstance(cites, list):
        for cite in cites:
            add(cite)
    elif isinstance(cites, str):
        add(cites)

    add(finding.get("citation_id"))
    add(finding.get("evidence_id"))
    ids = finding.get("citation_ids")
    if isinstance(ids, list):
        for item in ids:
            add(item)

    return out


def normalize_draft(result: dict[str, Any], packs: list[dict[str, Any]] | None = None) -> None:
    """Fill server-owned / derived fields so models need not restate them.

    Dimension and overall risk are derived from findings. Audit provenance is
    copied from Evidence Packs when omitted. Common draft shape mistakes
    (missing ids, dict parties, finding-level audit/human_review) are coerced
    or stripped so Web always receives a contract-shaped result.
    """
    result["schema_hint"] = LEGAL_REVIEW_V1
    result.setdefault("mode", "full")
    # Root-level parties is not in the contract.
    result.pop("parties", None)

    validation = result.get("validation")
    if not isinstance(validation, dict):
        validation = {}
        result["validation"] = validation
    validation.setdefault("status", "pending")
    validation.setdefault("errors", [])
    validation.setdefault("warnings", [])

    human = result.get("human_review")
    if not isinstance(human, dict):
        result["human_review"] = {"status": "not_required"}
    else:
        status = human.get("status") or "not_required"
        result["human_review"] = {"status": status}

    if result.get("review_status") in (None, ""):
        result["review_status"] = "pending"

    dim_risks: list[str] = []
    dims = result.get("dimensions")
    used_dim_ids: set[str] = set()
    used_finding_ids: set[str] = set()
    if isinstance(dims, list):
        for di, dim in enumerate(dims):
            if not isinstance(dim, dict):
                continue
            dim_id = dim.get("id")
            if not isinstance(dim_id, str) or not dim_id.strip():
                dim_id = slug_id(str(dim.get("name") or ""), fallback=f"dimension-{di + 1}")
            base = dim_id
            n = 2
            while dim_id in used_dim_ids:
                dim_id = f"{base}-{n}"
                n += 1
            dim["id"] = dim_id
            used_dim_ids.add(dim_id)
            if not isinstance(dim.get("name"), str) or not str(dim.get("name")).strip():
                dim["name"] = dim_id
            for key in list(dim.keys()):
                if key not in ("id", "name", "risk", "findings"):
                    dim.pop(key, None)

            findings = dim.get("findings")
            finding_risks: list[str] = []
            if isinstance(findings, list):
                for fi, finding in enumerate(findings):
                    if not isinstance(finding, dict):
                        continue
                    # Finding-level audit/human_review are not in the contract.
                    finding.pop("audit", None)
                    finding.pop("human_review", None)
                    parties = coerce_parties(finding.get("parties"))
                    if parties is None:
                        finding.pop("parties", None)
                    else:
                        finding["parties"] = parties

                    sug = finding.get("suggestion")
                    if isinstance(sug, dict):
                        finding["suggestion"] = str(sug.get("text") or sug.get("summary") or sug.get("content") or "").strip() or None
                    elif sug is not None and not isinstance(sug, str):
                        finding["suggestion"] = str(sug).strip() or None

                    # citations may arrive as bare ids or model aliases (citation_id).
                    finding["citations"] = coerce_citations(finding)
                    finding.pop("citation_id", None)
                    finding.pop("citation_ids", None)
                    finding.pop("evidence_id", None)

                    for key in list(finding.keys()):
                        if key not in (
                            "id",
                            "section",
                            "risk",
                            "confidence",
                            "text",
                            "suggestion",
                            "evidence",
                            "edit",
                            "citations",
                            "parties",
                        ):
                            finding.pop(key, None)

                    fid = finding.get("id")
                    if not isinstance(fid, str) or not fid.strip():
                        fid = slug_id(
                            str(finding.get("section") or finding.get("text") or ""),
                            fallback=f"{dim_id}-f{fi + 1}",
                        )
                    fbase = fid
                    n = 2
                    while fid in used_finding_ids:
                        fid = f"{fbase}-{n}"
                        n += 1
                    finding["id"] = fid
                    used_finding_ids.add(fid)

                    if not isinstance(finding.get("section"), str) or not str(finding.get("section")).strip():
                        finding["section"] = dim_id
                    if finding.get("confidence") not in ("high", "medium", "low"):
                        finding["confidence"] = "medium"

                    risk = finding.get("risk")
                    if isinstance(risk, str) and risk in RISK_ORDER:
                        finding_risks.append(risk)

            computed = max_risk(finding_risks) if finding_risks else "none"
            dim["risk"] = computed
            dim_risks.append(computed)

    if dim_risks or result.get("overall_risk") not in RISK_ORDER:
        result["overall_risk"] = max_risk(dim_risks)

    audit = result.get("audit")
    if not isinstance(audit, dict):
        audit = {}
        result["audit"] = audit
    first = next((p for p in (packs or []) if isinstance(p, dict)), {}) or {}
    if not audit.get("trace_id"):
        audit["trace_id"] = str(first.get("trace_id") or "")
    if not audit.get("knowledge_version"):
        audit["knowledge_version"] = str(first.get("knowledge_version") or "")
    if not isinstance(audit.get("spaces_queried"), list):
        audit["spaces_queried"] = []
    if not isinstance(audit.get("allowed_refs"), list):
        audit["allowed_refs"] = []
    if not isinstance(audit.get("pipeline_stages"), list) or not audit["pipeline_stages"]:
        audit["pipeline_stages"] = ["prepare", "retrieve", "draft"]
    for key in list(audit.keys()):
        if key not in ("trace_id", "knowledge_version", "spaces_queried", "allowed_refs", "pipeline_stages"):
            audit.pop(key, None)


def evidence_index(packs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for pack in packs:
        items = pack.get("items") if isinstance(pack, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                iid = item.get("id")
                if isinstance(iid, str) and iid.strip():
                    index[iid.strip()] = item
    return index


def enrich_citations(result: dict[str, Any], packs: list[dict[str, Any]]) -> None:
    """Fill display fields from Evidence Pack; grounding key remains citation.id."""
    from deerflow.knowledge.rag import user_attrs_from_metadata

    index = evidence_index(packs)
    if not index:
        return
    for _, finding in iter_findings(result):
        cites = finding.get("citations")
        if not isinstance(cites, list):
            continue
        for cite in cites:
            if not isinstance(cite, dict):
                continue
            cid = cite.get("id")
            if not isinstance(cid, str) or not cid.strip():
                continue
            ev = index.get(cid.strip())
            if not ev:
                continue
            if ev.get("citable_as"):
                cite["citable_as"] = ev["citable_as"]
            meta = ev.get("metadata") if isinstance(ev.get("metadata"), dict) else {}
            if meta.get("doc_id") and not cite.get("doc_id"):
                cite["doc_id"] = meta["doc_id"]
            if meta.get("page_no") is not None and cite.get("page_no") is None:
                cite["page_no"] = meta["page_no"]
            if meta.get("heading_path") and not cite.get("heading_path"):
                cite["heading_path"] = meta["heading_path"]
            attrs = user_attrs_from_metadata(meta)
            if attrs:
                cite["attrs"] = attrs


def build_references(result: dict[str, Any], packs: list[dict[str, Any]]) -> None:
    """Emit a top-level, deduped list of cited evidence with source text.

    Only grounded ids (present in the Evidence Pack) are included, so the
    references section is independently verifiable and cannot echo a
    hallucinated citation id.
    """
    from deerflow.knowledge.rag import user_attrs_from_metadata

    index = evidence_index(packs)
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    if index:
        for _, finding in iter_findings(result):
            cites = finding.get("citations")
            if not isinstance(cites, list):
                continue
            for cite in cites:
                cid = cite.get("id") if isinstance(cite, dict) else cite
                if not isinstance(cid, str):
                    continue
                cid = cid.strip()
                if not cid or cid in seen:
                    continue
                ev = index.get(cid)
                if not ev:
                    continue
                seen.add(cid)
                meta = ev.get("metadata") if isinstance(ev.get("metadata"), dict) else {}
                ref: dict[str, Any] = {
                    "id": cid,
                    "citable_as": ev.get("citable_as"),
                    "title": ev.get("title"),
                    "snippet": ev.get("snippet"),
                    "source": ev.get("source"),
                    "kind": ev.get("kind"),
                    "doc_id": meta.get("doc_id"),
                    "page_no": meta.get("page_no"),
                    "heading_path": meta.get("heading_path"),
                }
                attrs = user_attrs_from_metadata(meta)
                if attrs:
                    ref["attrs"] = attrs
                refs.append(ref)
    result["references"] = refs


def strip_edits(result: dict[str, Any]) -> None:
    """Failed reviews must not expose appliable body edits to Web clients."""
    for _, finding in iter_findings(result):
        edit = finding.get("edit")
        if not isinstance(edit, dict):
            finding.pop("edit", None)
            continue
        finding["edit"] = {"op": "none", "text": None}


def finalize_review(
    draft: dict[str, Any],
    *,
    allowed_ids: set[str] | None = None,
    evidence_packs: list[dict[str, Any]] | None = None,
    retrieval_empty: bool = False,
    strict: bool = True,
    source_sections: list[dict[str, Any]] | None = None,
    quote_pool: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], ValidationOutcome]:
    """
    Validate business rules, enrich citations, render report, set validation block.

    Default ``strict=True`` (provenance warnings become errors).
    Always overwrites ``report`` on success — never trust model-written Markdown.

    Skip path: ``review_status=draft`` or ``validation.status=skipped``.
    Normal Agent drafts use ``pending`` / ``pending`` and go through full validation.
    """
    result = copy.deepcopy(draft)
    result.pop("report", None)
    packs = evidence_packs or []
    ids = allowed_ids if allowed_ids is not None else allowed_ids_from_packs(packs)

    review_status = result.get("review_status")
    validation = result.get("validation")
    if not isinstance(validation, dict):
        validation = {}
        result["validation"] = validation

    if review_status == "draft" or validation.get("status") == "skipped":
        validation["status"] = "skipped"
        validation.setdefault("errors", [])
        validation.setdefault("warnings", [])
        return result, ValidationOutcome(status="skipped")

    normalize_draft(result, packs)

    empty = retrieval_empty or (ids is not None and len(ids) == 0)
    sections = source_sections if isinstance(source_sections, list) else None
    if sections:
        repair_quotes(result, source_sections=sections, quote_pool=quote_pool)
        errors, warnings = validate_review(
            result,
            ids,
            strict=strict,
            retrieval_empty=empty,
            source_sections=source_sections,
        )
        if any("quote not found" in err for err in errors):
            repair_quotes(result, source_sections=sections, quote_pool=quote_pool, relaxed=True)
            errors, warnings = validate_review(
                result,
                ids,
                strict=strict,
                retrieval_empty=empty,
                source_sections=source_sections,
            )
    else:
        errors, warnings = validate_review(
            result,
            ids,
            strict=strict,
            retrieval_empty=empty,
            source_sections=source_sections,
        )

    if not errors:
        enrich_citations(result, packs)
        build_references(result, packs)
        if isinstance(result.get("audit"), dict):
            result["audit"]["allowed_refs"] = sorted(ids) if ids else []
            stages = result["audit"].get("pipeline_stages")
            if isinstance(stages, list) and "validate" not in stages:
                stages = list(stages) + ["validate", "deliver"]
                result["audit"]["pipeline_stages"] = stages
        result["schema_hint"] = LEGAL_REVIEW_V1
        validation["status"] = "pass"
        validation["errors"] = []
        validation["warnings"] = warnings
        if result.get("review_status") not in ("approved", "rejected"):
            result["review_status"] = "machine_passed"
        # Render only after final status/provenance are set.
        result["report"] = render_report(result)
        _, schema_errors = parse_draft(result)
        if schema_errors:
            errors.extend(schema_errors)
            validation["status"] = "fail"
            validation["errors"] = errors
            result["review_status"] = "machine_failed"
            strip_edits(result)
            result["report"] = render_report(result)
        else:
            try:
                LegalReviewV1.model_validate(result)
            except Exception as exc:
                errors.append(str(exc))
                validation["status"] = "fail"
                validation["errors"] = errors
                result["review_status"] = "machine_failed"
                strip_edits(result)
                result["report"] = render_report(result)
    else:
        validation["status"] = "fail"
        validation["errors"] = errors
        validation["warnings"] = warnings
        result["review_status"] = "machine_failed"
        strip_edits(result)
        build_references(result, packs)
        if result.get("overall_risk") == "high":
            result["human_review"] = {"status": "required"}
        # Still render a readable report so Web is not stuck on raw JSONPath errors.
        result["report"] = render_report(result)
        if not str(result.get("summary") or "").strip():
            result["summary"] = "Machine validation failed; see report and validation errors."

    outcome = ValidationOutcome(
        status=str(validation["status"]),
        errors=list(validation.get("errors") or []),
        warnings=list(validation.get("warnings") or []),
    )
    return result, outcome
