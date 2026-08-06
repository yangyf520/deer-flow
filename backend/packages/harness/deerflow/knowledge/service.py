"""Knowledge domain: schemas, ACL, CRUD, search, agent tool."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Iterable
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.knowledge.rag import (
    delete_document_vectors,
    delete_space_vectors,
    evaluate_search_cases,
    get_scenario_config,
    ingest_document_text,
    merge_custom_metadata,
    merge_space_hits,
    parse_as_of,
    rank_by_temporal,
    rename_space_vectors,
    resolve_scenario,
    search_one_space,
    space_budgets,
    stable_rank_items,
    sync_document_metadata,
)
from deerflow.knowledge.rag import (
    list_document_chunks as rag_list_document_chunks,
)
from deerflow.persistence.knowledge.model import (
    KnowledgeDocumentRow,
    KnowledgeGrantRow,
    KnowledgeSpaceRow,
)
from deerflow.persistence.user.model import UserRow
from deerflow.utils.file_conversion import ParseResult, parse_file_bytes_with_fallback

logger = logging.getLogger(__name__)

_agent_knowledge_defaults: ContextVar[dict[str, Any] | None] = ContextVar("agent_knowledge_defaults", default=None)


def set_agent_knowledge_defaults(*, spaces: list[str] | None, scenario: str | None) -> Token | None:
    payload: dict[str, Any] = {}
    if spaces is not None:
        payload["spaces"] = spaces
    if scenario:
        payload["scenario"] = scenario
    return _agent_knowledge_defaults.set(payload)


def reset_agent_knowledge_defaults(token: Token | None) -> None:
    if token is not None:
        _agent_knowledge_defaults.reset(token)


def get_agent_knowledge_defaults() -> dict[str, Any]:
    return dict(_agent_knowledge_defaults.get() or {})


def resolve_agent_knowledge_scope(
    spaces: list[str] | None,
    scenario: str | None,
) -> tuple[list[str] | None, str | None]:
    """Restrict retrieval to the current Agent's knowledge binding.

    Outside an Agent run the request is unchanged. Within an Agent run, bound
    spaces are a hard ceiling (not merely defaults), and a bound scenario
    cannot be overridden by a tool call.
    """
    bound = _agent_knowledge_defaults.get()
    if bound is None:
        return spaces, scenario

    bound_spaces = bound.get("spaces")
    if bound_spaces is not None:
        allowed = set(bound_spaces)
        spaces = list(bound_spaces) if spaces is None else [space for space in spaces if space in allowed]

    bound_scenario = bound.get("scenario")
    if bound_scenario:
        scenario = str(bound_scenario)
    return spaces, scenario


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SPACE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


def knowledge_extra_available() -> bool:
    """True when LlamaIndex core is installed (store-specific deps checked at use time)."""
    try:
        import llama_index.core  # noqa: F401
    except ImportError:
        return False
    return True


def docling_extra_available() -> bool:
    try:
        import docling  # noqa: F401

        return True
    except ImportError:
        return False


def require_knowledge_extra() -> None:
    if not knowledge_extra_available():
        raise HTTPException(
            status_code=501,
            detail={
                "code": "not_implemented",
                "message": "Knowledge extra not installed. Run: uv sync --extra knowledge",
            },
        )


# ── schemas ────────────────────────────────────────────────────────────────


class SpaceCreateRequest(BaseModel):
    """Create a knowledge space.

    - ``name``: English machine-friendly display name (also used to derive id)
    - ``description``: Chinese / human-readable notes
    - ``id``: optional; auto-generated from ``name`` when omitted
    - ``scenario``: config scenarios[].type to bind (required for retrieval profile)
    """

    name: str = Field(min_length=1, max_length=256, description="English name")
    description: str | None = Field(default=None, description="Chinese description / notes")
    id: str | None = Field(default=None, min_length=1, max_length=64, description="Optional; auto from name")
    access: str = "open"
    allowed_kinds: list[str] = Field(default_factory=list)
    scenario: str | None = Field(default=None, description="Bound scenarios[].type from config")
    top_k: int | None = Field(default=None, ge=1, le=50)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    # Legacy alias → normalized into scenario
    default_scenarios: list[str] = Field(default_factory=list)


def space_knowledge_version(space: Any | None) -> str:
    """Published retrieval version for a space (stored in ``attrs``)."""
    if space is None:
        return "current"
    attrs = space.attrs if isinstance(getattr(space, "attrs", None), dict) else {}
    v = str(attrs.get("knowledge_version") or "current").strip()
    return v or "current"


def set_space_knowledge_version(space: Any, version: str) -> None:
    attrs = dict(space.attrs) if isinstance(getattr(space, "attrs", None), dict) else {}
    attrs["knowledge_version"] = (version or "current").strip() or "current"
    space.attrs = attrs


def space_retrieval_from_row(row: Any) -> tuple[int | None, float | None]:
    attrs = row.attrs if isinstance(getattr(row, "attrs", None), dict) else {}
    top_k = attrs.get("top_k")
    score = attrs.get("score")
    return (
        int(top_k) if top_k is not None else None,
        float(score) if score is not None else None,
    )


def apply_space_retrieval_attrs(space: Any, *, top_k: int | None, score: float | None) -> None:
    attrs = dict(space.attrs) if isinstance(getattr(space, "attrs", None), dict) else {}
    if top_k is not None:
        attrs["top_k"] = int(top_k)
    else:
        attrs.pop("top_k", None)
    if score is not None:
        attrs["score"] = float(score)
    else:
        attrs.pop("score", None)
    space.attrs = attrs


class SpaceUpdateRequest(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=64, description="Rename space id")
    name: str | None = None
    description: str | None = None
    access: str | None = None
    allowed_kinds: list[str] | None = None
    scenario: str | None = None
    default_scenarios: list[str] | None = None
    knowledge_version: str | None = Field(default=None, description="Published version label for retrieval")
    top_k: int | None = Field(default=None, ge=1, le=50)
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class SpaceResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    access: str
    owner_user_id: str
    allowed_kinds: list[str] = Field(default_factory=list)
    scenario: str | None = None
    default_scenarios: list[str] = Field(default_factory=list)
    knowledge_version: str = "current"
    top_k: int | None = None
    score: float | None = None
    my_role: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SpacesListResponse(BaseModel):
    items: list[SpaceResponse]
    total: int


class SpaceGrantRequest(BaseModel):
    subject_type: str = Field(pattern="^(user|dept)$")
    subject_id: str = Field(min_length=1, max_length=320)
    role: str = Field(pattern="^(viewer|editor|publisher|admin)$")


class SpaceGrantResponse(BaseModel):
    id: str
    space_id: str
    subject_type: str
    subject_id: str
    subject_name: str | None = None
    role: str
    granted_by: str | None = None
    expires_at: str | None = None
    created_at: str | None = None


class SpaceGrantsListResponse(BaseModel):
    items: list[SpaceGrantResponse]
    total: int


class ScenarioPackResponse(BaseModel):
    description: str = ""
    type: str
    label: str = ""
    space_id: str = ""
    host_space_id: str = ""


class ScenariosListResponse(BaseModel):
    items: list[ScenarioPackResponse]
    total: int


class ScenarioDefinitionRequest(BaseModel):
    """Create/update a knowledge scenario in pub_codes."""

    code: str = Field(min_length=1)
    label: str = Field(min_length=1)
    labels: dict[str, str] | None = None
    description: str = ""
    merge_mode: str = "slot_then_rrf"
    fusion_num_queries: int | None = None
    host_space_id: str | None = None


class MigrateCatalogHostRequest(BaseModel):
    host_space_id: str = Field(min_length=1)


class MigrateCatalogHostResponse(BaseModel):
    host_space_id: str
    updated: int


class KnowledgeKindResponse(BaseModel):
    id: str
    label: str = ""


class KindsListResponse(BaseModel):
    items: list[KnowledgeKindResponse]
    total: int


class KnowledgeTagResponse(BaseModel):
    id: str
    label: str = ""
    scenario: str = ""


class KnowledgeTagGroupResponse(BaseModel):
    id: str
    label: str = ""
    tags: list[str] = Field(default_factory=list)
    scenario: str = ""


class KnowledgeCatalogResponse(BaseModel):
    """Knowledge code catalog from DB (pub_codes); labels stored server-side."""

    kinds: list[KnowledgeKindResponse] = Field(default_factory=list)
    tags: list[KnowledgeTagResponse] = Field(default_factory=list)
    tag_groups: list[KnowledgeTagGroupResponse] = Field(default_factory=list)
    scenarios: list[ScenarioPackResponse] = Field(default_factory=list)


async def get_knowledge_catalog_from_db(session: AsyncSession, *, locale: str = "zh-CN") -> KnowledgeCatalogResponse:
    from deerflow.knowledge.catalog import get_catalog

    raw = await get_catalog(session, locale=locale)
    return KnowledgeCatalogResponse.model_validate(raw)


def ensure_kind_allowed(*, kind: str, space_allowed_kinds: list[str] | None) -> str:
    from fastapi import HTTPException

    kid = (kind or "").strip() or "general"
    cfg = get_knowledge_config()
    catalog = cfg.configured_kind_ids()
    # Optional global catalog: only enforce when operators listed kinds in YAML.
    if catalog and kid not in catalog:
        raise HTTPException(status_code=422, detail=f"unknown kind '{kid}'")
    allowed = [k for k in (space_allowed_kinds or []) if k]
    if allowed and kid not in allowed:
        raise HTTPException(status_code=422, detail=f"kind '{kid}' not allowed in this space")
    return kid


class DocumentResponse(BaseModel):
    id: str
    space_id: str
    title: str
    kind: str
    tags: list[str] = Field(default_factory=list)
    language: str
    sensitivity: str
    status: str
    source_filename: str
    source_uri: str
    content_type: str
    byte_size: int | None = None
    job_phase: str
    progress: int
    parse_quality: str | None = None
    parse_error: str | None = None
    error_message: str | None = None
    created_by: str
    created_by_name: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class DocumentsListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class DocumentChunkItem(BaseModel):
    id: str
    index: int
    text: str
    char_count: int
    block: str | None = None
    heading_path: str | None = None
    page: str | int | None = None
    parse_quality: str | None = None


class DocumentChunksResponse(BaseModel):
    doc_id: str
    title: str
    source_filename: str
    parse_quality: str | None = None
    parse_error: str | None = None
    items: list[DocumentChunkItem]
    total: int


class DocumentImportResponse(BaseModel):
    doc_id: str
    status: str
    job_phase: str
    progress: int
    deduped: bool = False
    message: str | None = None


class EmbedSegment(BaseModel):
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


def parse_embed_attrs_json(raw: str | None) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"invalid attrs JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="attrs must be a JSON object")
    return {str(k): v for k, v in parsed.items()}


def parse_embed_segments_json(raw: str | None) -> list[EmbedSegment] | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"invalid segments JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=422, detail="segments must be a JSON array")
    segments: list[EmbedSegment] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="each segment must be a JSON object")
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        meta = item.get("metadata")
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=422, detail="segment metadata must be a JSON object")
        segments.append(EmbedSegment(text=text, metadata=dict(meta or {})))
    if not segments:
        raise HTTPException(status_code=422, detail="segments must contain at least one non-empty text")
    return segments


class DocumentUpdateRequest(BaseModel):
    kind: str | None = None
    tags: list[str] | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    attrs: dict[str, Any] | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    spaces: list[str] | None = None
    scenario: str | None = None
    top_k: int | None = None
    knowledge_version: str = "current"


class RecallEvalCase(BaseModel):
    q: str = Field(min_length=1)
    needles: list[str] = Field(default_factory=list)
    relevant_doc_ids: list[str] = Field(default_factory=list)


class RecallEvalRequest(BaseModel):
    spaces: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    cases: list[RecallEvalCase] = Field(min_length=1)


class RecallEvalResponse(BaseModel):
    top_k: int
    case_count: int
    needle_hit_rate: float
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    labeled_case_count: int = 0
    cases: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str = ""


class EvidenceItem(BaseModel):
    id: str
    source: str
    kind: str
    title: str
    snippet: str
    score: float | None = None
    citable_as: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    attrs: dict[str, Any] | None = Field(
        default=None,
        description="Caller-defined fields from ingest (segments.metadata / document attrs); omitted when empty.",
    )


class EvidencePackResponse(BaseModel):
    knowledge_version: str
    trace_id: str
    items: list[EvidenceItem]
    answer: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── access ──────────────────────────────────────────────────────────────────

ROLE_RANK = {"viewer": 1, "editor": 2, "publisher": 3, "admin": 4}


def role_at_least(role: str | None, minimum: str) -> bool:
    if not role:
        return False
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(minimum, 99)


def _normalize_grant_subject_id(subject_id: str) -> str:
    from fastapi import HTTPException

    value = subject_id.strip()
    if not value:
        raise HTTPException(status_code=422, detail="subject_id is required")
    return value


def _effective_dept_ids(dept_ids: list[str] | None = None) -> list[str]:
    """Dept ids from explicit arg or upstream session (never from local org catalog)."""
    if dept_ids is not None:
        return [str(d).strip() for d in dept_ids if str(d).strip()]
    from deerflow.runtime.user_context import get_current_user

    user = get_current_user()
    if user is None:
        return []
    raw = getattr(user, "dept_ids", None)
    if isinstance(raw, list):
        return [str(d).strip() for d in raw if str(d).strip()]
    return []


async def resolve_space_role(
    session: AsyncSession,
    *,
    user_id: str,
    system_role: str,
    space: KnowledgeSpaceRow,
    dept_ids: list[str] | None = None,
) -> str | None:
    cfg = get_knowledge_config().authz
    if cfg.system_admin_is_space_admin and system_role == "admin":
        return "admin"
    if space.owner_user_id == user_id:
        return "admin"
    roles: list[str] = []
    user_result = await session.execute(
        select(KnowledgeGrantRow.role).where(
            KnowledgeGrantRow.resource_type == "space",
            KnowledgeGrantRow.resource_id == space.id,
            KnowledgeGrantRow.subject_type == "user",
            KnowledgeGrantRow.subject_id == user_id,
            or_(KnowledgeGrantRow.expires_at.is_(None), KnowledgeGrantRow.expires_at > _now()),
        )
    )
    roles.extend(role for role in user_result.scalars().all() if role in ROLE_RANK)
    effective_dept_ids = _effective_dept_ids(dept_ids)
    if effective_dept_ids:
        dept_result = await session.execute(
            select(KnowledgeGrantRow.role).where(
                KnowledgeGrantRow.resource_type == "space",
                KnowledgeGrantRow.resource_id == space.id,
                KnowledgeGrantRow.subject_type == "dept",
                KnowledgeGrantRow.subject_id.in_(effective_dept_ids),
                or_(KnowledgeGrantRow.expires_at.is_(None), KnowledgeGrantRow.expires_at > _now()),
            )
        )
        roles.extend(role for role in dept_result.scalars().all() if role in ROLE_RANK)
    if roles:
        return max(roles, key=lambda role: ROLE_RANK[role])
    if space.access == "open":
        return "viewer"
    return None


def _slugify_space_id(name: str) -> str:
    """Derive a stable space id from an English name."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "space"
    return slug[:48]


def normalize_space_id(raw: str) -> str:
    """Normalize user input into a stable knowledge space id."""
    text = (raw or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="space id is required")
    lowered = text.lower()
    if _SPACE_ID_RE.fullmatch(lowered):
        return lowered
    slug = _slugify_space_id(text)
    if not slug or slug == "space":
        raise HTTPException(status_code=422, detail="invalid space id")
    return slug[:64]


async def rename_space_id(session: AsyncSession, *, old_id: str, new_id: str) -> None:
    """Rename a knowledge space primary key and update dependent rows."""
    from deerflow.knowledge.catalog import rename_catalog_space_references
    from deerflow.persistence.knowledge.model import KnowledgeDocumentRow, KnowledgeGrantRow, KnowledgeSpaceRow

    target = normalize_space_id(new_id)
    if target == old_id:
        return
    if await session.get(KnowledgeSpaceRow, target):
        raise HTTPException(status_code=409, detail="space id already exists")

    old = await session.get(KnowledgeSpaceRow, old_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Space not found")

    session.add(
        KnowledgeSpaceRow(
            id=target,
            name=old.name,
            description=old.description,
            access=old.access,
            owner_user_id=old.owner_user_id,
            allowed_kinds=list(old.allowed_kinds or []),
            default_scenarios=list(old.default_scenarios or []),
            schema_version=old.schema_version,
            attrs=dict(old.attrs or {}),
            created_at=old.created_at,
            updated_at=_now(),
        )
    )
    await session.flush()

    await session.execute(update(KnowledgeDocumentRow).where(KnowledgeDocumentRow.space_id == old_id).values(space_id=target))
    await session.execute(update(KnowledgeGrantRow).where(KnowledgeGrantRow.space_id == old_id).values(space_id=target))
    await session.execute(
        update(KnowledgeGrantRow)
        .where(
            KnowledgeGrantRow.resource_type == "space",
            KnowledgeGrantRow.resource_id == old_id,
        )
        .values(resource_id=target)
    )
    await rename_catalog_space_references(session, old_id=old_id, new_id=target)
    await session.delete(old)
    await session.flush()
    await asyncio.to_thread(rename_space_vectors, old_id=old_id, new_id=target)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_optional_iso_dt(raw: str | None) -> datetime | None:
    if raw is None or not str(raw).strip():
        return None
    return parse_as_of(str(raw).strip())


def _resolve_search_space_ids(spaces: list[str] | None, allowed_ids: set[str]) -> list[str]:
    """Resolve caller space ids against ACL.

    - ``None``: all accessible spaces (direct API / explicit session widen)
    - ``[]``: no spaces (unbound agent or session disabled)
    - non-empty list: intersection with ACL
    """
    if spaces is None:
        return list(allowed_ids)
    if not spaces:
        return []
    return [s for s in spaces if s in allowed_ids]


async def resolve_bound_scenario(
    session: AsyncSession,
    scenario: str | None,
    default_scenarios: list[str] | None = None,
) -> str:
    from deerflow.knowledge.catalog import validate_scenario_code

    raw = (scenario or "").strip()
    if not raw and default_scenarios:
        raw = str(default_scenarios[0] or "").strip()
    return await validate_scenario_code(session, raw)


def resolve_space_allowed_kinds(requested: list[str] | None = None) -> list[str]:
    """Space document kind whitelist: optional YAML catalog + caller subset."""
    cfg = get_knowledge_config()
    want = [k for k in (requested or []) if k]
    catalog = cfg.configured_kind_ids()
    if not want:
        return list(catalog) if catalog else ["general"]
    if catalog:
        unknown = [k for k in want if k not in catalog]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown kind(s): {unknown}")
    return want


def space_to_response(row: KnowledgeSpaceRow, my_role: str | None = None) -> SpaceResponse:
    scenarios = list(row.default_scenarios or [])
    bound = scenarios[0] if scenarios else None
    top_k, score = space_retrieval_from_row(row)
    return SpaceResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        access=row.access,
        owner_user_id=row.owner_user_id,
        allowed_kinds=list(row.allowed_kinds or []),
        scenario=bound,
        default_scenarios=scenarios,
        knowledge_version=space_knowledge_version(row),
        top_k=top_k,
        score=score,
        my_role=my_role,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def doc_to_response(row: KnowledgeDocumentRow, *, created_by_name: str | None = None) -> DocumentResponse:
    return DocumentResponse(
        id=row.id,
        space_id=row.space_id,
        title=row.title,
        kind=row.kind,
        tags=[str(t) for t in (row.tags or []) if str(t).strip()],
        language=row.language,
        sensitivity=row.sensitivity,
        status=row.status,
        source_filename=row.source_filename,
        source_uri=row.source_uri,
        content_type=row.content_type,
        byte_size=row.byte_size,
        job_phase=row.job_phase,
        progress=row.progress,
        parse_quality=row.parse_quality,
        parse_error=row.parse_error,
        error_message=row.error_message,
        created_by=row.created_by,
        created_by_name=created_by_name,
        effective_from=_iso(row.effective_from),
        effective_to=_iso(row.effective_to),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        attrs=dict(row.attrs or {}) if isinstance(getattr(row, "attrs", None), dict) else {},
    )


def _display_name_from_email(email: str | None, user_id: str) -> str:
    raw = (email or "").strip()
    if not raw:
        return user_id
    local = raw.split("@", 1)[0].strip()
    return local or raw


async def resolve_user_display_names(session: AsyncSession, user_ids: Iterable[str]) -> dict[str, str]:
    """Map user_id → display name (email local-part). Missing users omitted."""
    ids = sorted({str(u).strip() for u in user_ids if u and str(u).strip()})
    if not ids:
        return {}
    from deerflow.persistence.user.model import UserRow

    rows = list((await session.execute(select(UserRow).where(UserRow.id.in_(ids)))).scalars().all())
    return {r.id: _display_name_from_email(r.email, r.id) for r in rows}


async def list_accessible_spaces(
    session: AsyncSession,
    *,
    user_id: str,
    system_role: str,
) -> list[SpaceResponse]:
    result = await session.execute(select(KnowledgeSpaceRow))
    spaces = list(result.scalars().all())
    out: list[SpaceResponse] = []
    for space in spaces:
        role = await resolve_space_role(
            session,
            user_id=user_id,
            system_role=system_role,
            space=space,
        )
        if role:
            out.append(space_to_response(space, my_role=role))
    return out


async def get_space_or_404(
    session: AsyncSession,
    *,
    space_id: str,
    user_id: str,
    system_role: str,
    min_role: str = "viewer",
) -> tuple[KnowledgeSpaceRow, str]:
    from fastapi import HTTPException

    space = await session.get(KnowledgeSpaceRow, space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="Space not found")
    role = await resolve_space_role(
        session,
        user_id=user_id,
        system_role=system_role,
        space=space,
    )
    if not role_at_least(role, min_role):
        raise HTTPException(status_code=404, detail="Space not found")
    assert role is not None
    return space, role


async def create_space(
    session: AsyncSession,
    *,
    user_id: str,
    name: str,
    description: str | None,
    access: str,
    allowed_kinds: list[str],
    scenario: str | None = None,
    default_scenarios: list[str] | None = None,
    space_id: str | None = None,
    top_k: int | None = None,
    score: float | None = None,
) -> SpaceResponse:

    raw_scenario = (scenario or "").strip()
    legacy = default_scenarios or []
    if raw_scenario or legacy:
        bound = await resolve_bound_scenario(session, scenario, default_scenarios)
        kinds = resolve_space_allowed_kinds(allowed_kinds)
        scenarios_list = [bound]
    else:
        scenarios_list = []
        cfg = get_knowledge_config()
        want = [k for k in (allowed_kinds or []) if k]
        catalog = cfg.configured_kind_ids()
        if want:
            if catalog:
                unknown = [k for k in want if k not in catalog]
                if unknown:
                    raise HTTPException(status_code=422, detail=f"unknown kind(s): {unknown}")
            kinds = want
        else:
            kinds = list(catalog) if catalog else []

    base_id = normalize_space_id(space_id) if (space_id or "").strip() else _slugify_space_id(name)
    candidate = base_id
    # Avoid collisions: legal, legal-2, legal-3...
    for i in range(2, 50):
        existing = await session.get(KnowledgeSpaceRow, candidate)
        if existing is None:
            break
        candidate = f"{base_id[:40]}-{i}"
    else:
        candidate = f"{base_id[:40]}-{uuid.uuid4().hex[:8]}"

    now = _now()
    row = KnowledgeSpaceRow(
        id=candidate,
        name=name.strip(),
        description=(description.strip() if description else None) or None,
        access=access if access in ("open", "members", "private") else "open",
        owner_user_id=user_id,
        allowed_kinds=kinds,
        default_scenarios=scenarios_list,
        created_at=now,
        updated_at=now,
    )
    apply_space_retrieval_attrs(row, top_k=top_k, score=score)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return space_to_response(row, my_role="admin")


async def ensure_catalog_scenario_space(
    session: AsyncSession,
    *,
    user_id: str,
    scenario_code: str,
    label: str,
    space_id: str | None = None,
) -> str:
    """Ensure a knowledge space exists for a catalog scenario (1:1 by default)."""
    from deerflow.persistence.knowledge.model import KnowledgeSpaceRow

    sid = (scenario_code or "").strip()
    if not sid:
        raise HTTPException(status_code=422, detail="scenario code is required")
    linked_id = (space_id or sid).strip() or sid
    display = (label or sid).strip() or sid
    existing = await session.get(KnowledgeSpaceRow, linked_id)
    if existing is None:
        await create_space(
            session,
            user_id=user_id,
            name=display,
            description=None,
            access="open",
            allowed_kinds=[],
            scenario=sid,
            space_id=linked_id,
            top_k=8,
            score=0.35,
        )
        return linked_id
    existing.name = display
    existing.default_scenarios = [sid]
    existing.updated_at = _now()
    await session.commit()
    return linked_id


async def delete_scenario_cascade(
    session: AsyncSession,
    *,
    user_id: str,
    system_role: str,
    code: str,
) -> bool:
    """Delete catalog scenario and its linked knowledge space."""
    from deerflow.knowledge.catalog import delete_scenario as delete_scenario_row
    from deerflow.persistence.knowledge.model import KnowledgeSpaceRow

    deleted, space_id = await delete_scenario_row(session, code)
    if not deleted:
        return False
    if not space_id:
        return True
    space = await session.get(KnowledgeSpaceRow, space_id)
    if space is None:
        return True
    try:
        await delete_space(
            session,
            space_id=space_id,
            user_id=user_id,
            system_role=system_role,
        )
    except HTTPException as exc:
        if exc.status_code not in (403, 404):
            raise
        logger.warning(
            "catalog scenario %s deleted but space %s was not removed: %s",
            code,
            space_id,
            exc.detail,
        )
    return True


async def update_space(
    session: AsyncSession,
    *,
    space_id: str,
    user_id: str,
    system_role: str,
    body: SpaceUpdateRequest,
) -> SpaceResponse:
    """Update space fields; rebind scenario whitelist when scenario changes."""
    space, _ = await get_space_or_404(
        session,
        space_id=space_id,
        user_id=user_id,
        system_role=system_role,
        min_role="admin",
    )
    if body.id is not None:
        new_id = normalize_space_id(body.id)
        if new_id != space_id:
            await rename_space_id(session, old_id=space_id, new_id=new_id)
            space = await session.get(KnowledgeSpaceRow, new_id)
            if space is None:
                raise HTTPException(status_code=404, detail="Space not found")
    if body.name is not None:
        space.name = body.name
    if body.description is not None:
        space.description = body.description
    if body.access is not None:
        space.access = body.access
    if body.scenario is not None or body.default_scenarios is not None:
        bound = await resolve_bound_scenario(session, body.scenario, body.default_scenarios)
        space.default_scenarios = [bound]
        if body.allowed_kinds is not None:
            space.allowed_kinds = resolve_space_allowed_kinds(body.allowed_kinds)
        else:
            space.allowed_kinds = resolve_space_allowed_kinds(None)
    elif body.allowed_kinds is not None:
        await resolve_bound_scenario(session, None, list(space.default_scenarios or []))
        space.allowed_kinds = resolve_space_allowed_kinds(body.allowed_kinds)
    if body.knowledge_version is not None:
        set_space_knowledge_version(space, body.knowledge_version)
    if body.top_k is not None or body.score is not None:
        existing_top_k, existing_score = space_retrieval_from_row(space)
        apply_space_retrieval_attrs(
            space,
            top_k=body.top_k if body.top_k is not None else existing_top_k,
            score=body.score if body.score is not None else existing_score,
        )
    await session.commit()
    await session.refresh(space)
    return space_to_response(space, my_role="admin")


def _grant_response(row: KnowledgeGrantRow, subject_name: str | None = None) -> SpaceGrantResponse:
    return SpaceGrantResponse(
        id=row.id,
        space_id=row.space_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_name=subject_name or row.subject_id,
        role=row.role,
        granted_by=row.granted_by,
        expires_at=_iso(row.expires_at),
        created_at=_iso(row.created_at),
    )


async def list_grants(session: AsyncSession, space_id: str) -> list[SpaceGrantResponse]:
    rows = list(
        (
            await session.execute(
                select(KnowledgeGrantRow)
                .where(
                    KnowledgeGrantRow.resource_type == "space",
                    KnowledgeGrantRow.resource_id == space_id,
                )
                .order_by(KnowledgeGrantRow.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_grant_response(row) for row in rows]


async def upsert_grant(
    session: AsyncSession,
    *,
    space_id: str,
    subject_type: str,
    subject_id: str,
    role: str,
    granted_by: str,
) -> SpaceGrantResponse:
    if subject_type not in {"user", "dept"}:
        raise HTTPException(status_code=422, detail="Invalid subject_type")
    if role not in ROLE_RANK:
        raise HTTPException(status_code=422, detail="Invalid role")
    resolved_subject_id = _normalize_grant_subject_id(subject_id)
    row = await session.scalar(
        select(KnowledgeGrantRow).where(
            KnowledgeGrantRow.resource_type == "space",
            KnowledgeGrantRow.resource_id == space_id,
            KnowledgeGrantRow.subject_type == subject_type,
            KnowledgeGrantRow.subject_id == resolved_subject_id,
        )
    )
    now = _now()
    if row is None:
        row = KnowledgeGrantRow(
            id=str(uuid.uuid4()),
            resource_type="space",
            resource_id=space_id,
            space_id=space_id,
            subject_type=subject_type,
            subject_id=resolved_subject_id,
            role=role,
            granted_by=granted_by,
            created_at=now,
        )
        session.add(row)
    else:
        row.role = role
        row.granted_by = granted_by
    await session.commit()
    await session.refresh(row)
    return _grant_response(row)


async def delete_grant(
    session: AsyncSession,
    *,
    space_id: str,
    subject_type: str,
    subject_id: str,
) -> None:
    if subject_type not in {"user", "dept"}:
        raise HTTPException(status_code=404, detail="Grant not found")
    resolved_subject_id = _normalize_grant_subject_id(subject_id)
    row = await session.scalar(
        select(KnowledgeGrantRow).where(
            KnowledgeGrantRow.resource_type == "space",
            KnowledgeGrantRow.resource_id == space_id,
            KnowledgeGrantRow.subject_type == subject_type,
            KnowledgeGrantRow.subject_id == resolved_subject_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    await session.delete(row)
    await session.commit()


async def search_users(session: AsyncSession, query: str, limit: int = 20) -> list[dict[str, str]]:
    term = query.strip().lower()
    stmt = select(UserRow).order_by(UserRow.email).limit(limit)
    if term:
        stmt = stmt.where(func.lower(UserRow.email).contains(term))
    rows = list((await session.execute(stmt)).scalars().all())
    return [{"id": row.id, "email": row.email, "name": _display_name_from_email(row.email, row.id)} for row in rows]


async def list_documents(
    session: AsyncSession,
    space_id: str,
    *,
    kind: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[DocumentResponse], int]:
    filters = [KnowledgeDocumentRow.space_id == space_id]
    kind_filter = (kind or "").strip()
    if kind_filter:
        filters.append(KnowledgeDocumentRow.kind == kind_filter)
    q_filter = (q or "").strip()
    if q_filter:
        pattern = f"%{q_filter}%"
        filters.append(
            or_(
                KnowledgeDocumentRow.title.ilike(pattern),
                KnowledgeDocumentRow.source_filename.ilike(pattern),
            )
        )

    total = await session.scalar(select(func.count()).select_from(KnowledgeDocumentRow).where(*filters))
    result = await session.execute(select(KnowledgeDocumentRow).where(*filters).order_by(KnowledgeDocumentRow.created_at.desc()).limit(limit).offset(offset))
    rows = list(result.scalars().all())
    names = await resolve_user_display_names(session, [r.created_by for r in rows])
    return [doc_to_response(r, created_by_name=names.get(r.created_by)) for r in rows], int(total or 0)


async def get_document_chunks(
    session: AsyncSession,
    *,
    space_id: str,
    doc_id: str,
) -> DocumentChunksResponse:
    from fastapi import HTTPException

    row = await session.get(KnowledgeDocumentRow, doc_id)
    if row is None or row.space_id != space_id:
        raise HTTPException(status_code=404, detail="Document not found")
    raw = await asyncio.to_thread(rag_list_document_chunks, space_id=space_id, doc_id=doc_id)
    items = [DocumentChunkItem.model_validate(x) for x in raw]
    return DocumentChunksResponse(
        doc_id=row.id,
        title=row.title,
        source_filename=row.source_filename,
        parse_quality=row.parse_quality,
        parse_error=row.parse_error,
        items=items,
        total=len(items),
    )


async def delete_document(
    session: AsyncSession,
    *,
    space_id: str,
    doc_id: str,
) -> None:
    """Delete vectors (best-effort), then the document DB row."""
    from fastapi import HTTPException

    row = await session.get(KnowledgeDocumentRow, doc_id)
    if row is None or row.space_id != space_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        await asyncio.to_thread(delete_document_vectors, space_id=space_id, doc_id=doc_id)
    except Exception as exc:
        # Prefer removing the DB row over leaving an undeletable failed ingest.
        logger.exception("vector delete failed for %s (continuing with DB delete): %s", doc_id, exc)

    try:
        await session.delete(row)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("db delete failed for %s", doc_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document. {exc}",
        ) from exc


async def delete_all_documents(
    session: AsyncSession,
    *,
    space_id: str,
) -> int:
    """Delete every document in a space (vectors best-effort, then DB rows)."""
    from fastapi import HTTPException

    result = await session.execute(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.space_id == space_id))
    docs = list(result.scalars().all())
    if not docs:
        return 0

    for row in docs:
        try:
            await asyncio.to_thread(
                delete_document_vectors,
                space_id=space_id,
                doc_id=row.id,
            )
        except Exception as exc:
            logger.exception(
                "vector delete failed for %s (continuing with DB delete): %s",
                row.id,
                exc,
            )

    try:
        for row in docs:
            await session.delete(row)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("bulk document delete failed for space %s", space_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete documents. {exc}",
        ) from exc

    return len(docs)


async def delete_space(
    session: AsyncSession,
    *,
    space_id: str,
    user_id: str,
    system_role: str,
) -> None:
    """Delete a space and cascade: vectors → DB (grants+docs via FK).

    Requires space admin (or system admin per authz config).
    """
    from fastapi import HTTPException

    space, _ = await get_space_or_404(
        session,
        space_id=space_id,
        user_id=user_id,
        system_role=system_role,
        min_role="admin",
    )

    result = await session.execute(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.space_id == space_id))
    docs = list(result.scalars().all())
    doc_ids = [d.id for d in docs]

    try:
        for did in doc_ids:
            await asyncio.to_thread(delete_document_vectors, space_id=space_id, doc_id=did)
        await asyncio.to_thread(delete_space_vectors, space_id=space_id)
    except Exception as exc:
        # Prefer removing the DB row over leaving an undeletable space.
        logger.exception("space vector delete failed for %s (continuing with DB delete): %s", space_id, exc)

    try:
        await session.delete(space)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("space db delete failed for %s", space_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete space. {exc}",
        ) from exc


async def import_document(
    session_factory: async_sessionmaker,
    *,
    space_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    data: bytes,
    title: str | None = None,
    kind: str = "general",
    tags: list[str] | None = None,
    attrs: dict[str, Any] | None = None,
    segments: list[EmbedSegment] | None = None,
) -> DocumentImportResponse:
    from fastapi import HTTPException

    if not data and not segments:
        raise HTTPException(status_code=400, detail="file or segments required")

    if segments:
        payload = json.dumps([s.model_dump() for s in segments], ensure_ascii=False, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
    else:
        checksum = hashlib.sha256(data).hexdigest()

    async with session_factory() as session:
        space = await session.get(KnowledgeSpaceRow, space_id)
        if space is None:
            raise HTTPException(status_code=404, detail="Space not found")
        kind = ensure_kind_allowed(kind=kind, space_allowed_kinds=list(space.allowed_kinds or []))
        tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()]

        # Same bytes in the same space → reuse (no duplicate vectors).
        existing = (
            (
                await session.execute(
                    select(KnowledgeDocumentRow).where(
                        KnowledgeDocumentRow.space_id == space_id,
                        KnowledgeDocumentRow.checksum_sha256 == checksum,
                        KnowledgeDocumentRow.status.in_(("ready", "processing")),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            if attrs:
                merged_attrs = dict(existing.attrs or {}) if isinstance(existing.attrs, dict) else {}
                merged_attrs.update(merge_custom_metadata({}, attrs))
                existing.attrs = merged_attrs
                existing.updated_at = _now()
                await session.commit()
            logger.info(
                "import deduped space=%s checksum=%s existing=%s",
                space_id,
                checksum[:12],
                existing.id,
            )
            return DocumentImportResponse(
                doc_id=existing.id,
                status=existing.status,
                job_phase=existing.job_phase,
                progress=existing.progress,
                deduped=True,
                message=None,
            )

        # Failed prior upload with same checksum → replace (delete old shards first).
        failed = (
            (
                await session.execute(
                    select(KnowledgeDocumentRow).where(
                        KnowledgeDocumentRow.space_id == space_id,
                        KnowledgeDocumentRow.checksum_sha256 == checksum,
                        KnowledgeDocumentRow.status == "failed",
                    )
                )
            )
            .scalars()
            .first()
        )
        if failed is not None:
            await delete_document(session, space_id=space_id, doc_id=failed.id)

        doc_id = str(uuid.uuid4())
        now = _now()
        default_title = Path(filename).stem.strip() or filename
        doc_attrs = merge_custom_metadata({}, attrs)
        row = KnowledgeDocumentRow(
            id=doc_id,
            space_id=space_id,
            title=title or default_title,
            kind=kind or "general",
            tags=tag_list,
            attrs=doc_attrs,
            status="processing",
            source_filename=filename,
            source_uri="",
            content_type=content_type or "application/octet-stream",
            byte_size=len(data) if data else None,
            checksum_sha256=checksum,
            job_phase="queued",
            progress=0,
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        response = DocumentImportResponse(
            doc_id=row.id,
            status=row.status,
            job_phase=row.job_phase,
            progress=row.progress,
            deduped=False,
            message=None,
        )

    # background ingest
    segment_payload = [s.model_dump() for s in segments] if segments else None
    asyncio.create_task(
        _run_ingest(
            session_factory,
            doc_id=doc_id,
            data=data,
            filename=filename,
            segments=segment_payload,
        )
    )
    return response


async def _parse_upload_bytes(data: bytes, filename: str) -> ParseResult:
    """Parse uploaded bytes with optional ``knowledge.parse.timeout_seconds``."""
    timeout = get_knowledge_config().parse.timeout_seconds

    def _parse() -> ParseResult:
        parsed, _backend = parse_file_bytes_with_fallback(data, filename)
        return parsed

    coro = asyncio.to_thread(_parse)
    if timeout > 0:
        try:
            return await asyncio.wait_for(coro, timeout=float(timeout))
        except TimeoutError:
            return ParseResult(
                text="",
                parse_quality="failed",
                error=f"parse timed out after {timeout}s",
            )
    return await coro


async def _run_ingest(
    session_factory: async_sessionmaker,
    *,
    doc_id: str,
    data: bytes,
    filename: str,
    segments: list[dict[str, Any]] | None = None,
) -> None:
    async with session_factory() as session:
        row = await session.get(KnowledgeDocumentRow, doc_id)
        if row is None:
            return
        try:
            row.job_phase = "parsing"
            row.progress = 20
            row.updated_at = _now()
            await session.commit()

            structured_docs = None
            parsed_text = ""
            parse_quality = "ok"
            parse_error = None
            if segments:
                from llama_index.core import Document

                structured_docs = [Document(text=str(seg.get("text") or "").strip(), metadata=dict(seg.get("metadata") or {})) for seg in segments if str(seg.get("text") or "").strip()]
                parsed_text = "\n\n".join(str(seg.get("text") or "").strip() for seg in segments)
            else:
                parsed = await _parse_upload_bytes(data, filename)
                parse_quality = parsed.parse_quality
                parse_error = parsed.error
                parsed_text = parsed.text
                if parsed.parse_quality == "failed" or not parsed.text.strip():
                    row.parse_quality = parsed.parse_quality
                    row.parse_error = parsed.error
                    row.status = "failed"
                    row.job_phase = "failed"
                    row.progress = 100
                    row.error_message = parsed.error or "parse failed"
                    row.updated_at = _now()
                    await session.commit()
                    return

            row.parse_quality = parse_quality
            row.parse_error = parse_error
            if not parsed_text.strip():
                row.status = "failed"
                row.job_phase = "failed"
                row.progress = 100
                row.error_message = parse_error or "empty content"
                row.updated_at = _now()
                await session.commit()
                return

            row.job_phase = "embedding"
            row.progress = 60
            row.updated_at = _now()
            await session.commit()

            space = await session.get(KnowledgeSpaceRow, row.space_id)
            release = space_knowledge_version(space)
            doc_attrs = dict(row.attrs or {}) if isinstance(row.attrs, dict) else {}

            await asyncio.to_thread(
                ingest_document_text,
                space_id=row.space_id,
                doc_id=row.id,
                title=row.title,
                kind=row.kind,
                sensitivity=row.sensitivity,
                text=parsed_text,
                parse_quality=parse_quality,
                documents=structured_docs,
                tags=list(row.tags or []),
                release=release,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                doc_attrs=doc_attrs,
            )

            row.status = "ready"
            row.job_phase = "ready"
            row.progress = 100
            row.updated_at = _now()
            await session.commit()
        except Exception as exc:
            logger.exception("ingest failed for %s", doc_id)
            row.status = "failed"
            row.job_phase = "failed"
            row.progress = 100
            row.error_message = str(exc)
            row.updated_at = _now()
            await session.commit()


async def reindex_document(
    session_factory: async_sessionmaker,
    *,
    space_id: str,
    doc_id: str,
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> DocumentResponse:
    """Re-parse + re-embed an existing document from uploaded file bytes."""
    if not data:
        raise HTTPException(status_code=422, detail="file required for reindex")

    checksum = hashlib.sha256(data).hexdigest()
    async with session_factory() as session:
        row = await session.get(KnowledgeDocumentRow, doc_id)
        if row is None or row.space_id != space_id:
            raise HTTPException(status_code=404, detail="Document not found")
        if row.status == "processing":
            raise HTTPException(status_code=409, detail="Document is already processing")
        safe_filename = (filename or row.source_filename or "file.bin").strip() or "file.bin"
        row.source_filename = safe_filename
        if content_type:
            row.content_type = content_type
        row.byte_size = len(data)
        row.checksum_sha256 = checksum
        row.source_uri = ""
        row.status = "processing"
        row.job_phase = "queued"
        row.progress = 0
        row.error_message = None
        row.parse_error = None
        row.updated_at = _now()
        await session.commit()
        await session.refresh(row)
        names = await resolve_user_display_names(session, [row.created_by])
        response = doc_to_response(row, created_by_name=names.get(row.created_by))

    asyncio.create_task(_run_ingest(session_factory, doc_id=doc_id, data=data, filename=safe_filename))
    return response


async def update_document(
    session: AsyncSession,
    *,
    space_id: str,
    doc_id: str,
    kind: str | None = None,
    tags: list[str] | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    title: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> DocumentResponse:
    row = await session.get(KnowledgeDocumentRow, doc_id)
    if row is None or row.space_id != space_id:
        raise HTTPException(status_code=404, detail="Document not found")

    space = await session.get(KnowledgeSpaceRow, space_id)
    meta_patch: dict[str, Any] = {}

    if title is not None:
        row.title = title.strip()
        meta_patch["title"] = row.title
    if kind is not None:
        kid = ensure_kind_allowed(kind=kind, space_allowed_kinds=list(space.allowed_kinds or []) if space else [])
        row.kind = kid
        meta_patch["kind"] = kid
    if tags is not None:
        row.tags = [str(t).strip() for t in tags if str(t).strip()]
        meta_patch["tags"] = ",".join(row.tags or [])
    if effective_from is not None:
        row.effective_from = _parse_optional_iso_dt(effective_from)
        if row.effective_from is not None:
            meta_patch["effective_from"] = row.effective_from.isoformat()
    if effective_to is not None:
        row.effective_to = _parse_optional_iso_dt(effective_to)
        if row.effective_to is not None:
            meta_patch["effective_to"] = row.effective_to.isoformat()
    if attrs is not None:
        merged_attrs = dict(row.attrs or {}) if isinstance(row.attrs, dict) else {}
        merged_attrs.update(merge_custom_metadata({}, attrs))
        row.attrs = merged_attrs
        meta_patch.update(merge_custom_metadata({}, attrs))
    row.updated_at = _now()
    await session.commit()
    await session.refresh(row)

    if space is not None:
        meta_patch.setdefault("release", space_knowledge_version(space))
    if meta_patch:
        await asyncio.to_thread(
            sync_document_metadata,
            space_id=space_id,
            doc_id=doc_id,
            patch=meta_patch,
        )

    names = await resolve_user_display_names(session, [row.created_by])
    return doc_to_response(row, created_by_name=names.get(row.created_by))


async def eval_recall(
    session: AsyncSession,
    *,
    user_id: str,
    system_role: str,
    spaces: list[str] | None,
    cases: list[RecallEvalCase],
    top_k: int = 5,
) -> RecallEvalResponse:
    """Run Precision@k / Recall@k / needle eval on accessible spaces."""
    accessible = await list_accessible_spaces(session, user_id=user_id, system_role=system_role)
    allowed_ids = {s.id for s in accessible}
    space_ids = _resolve_search_space_ids(spaces, allowed_ids)
    if not space_ids:
        raise HTTPException(status_code=403, detail="No accessible spaces for eval")

    payload = [c.model_dump() for c in cases]
    result = await asyncio.to_thread(
        evaluate_search_cases,
        space_ids=space_ids,
        cases=payload,
        top_k=top_k,
    )

    # Attach document provenance (title / filename) for UI source lines.
    doc_ids: set[str] = set()
    for case in result.get("cases") or []:
        for item in case.get("items") or []:
            did = item.get("doc_id")
            if did:
                doc_ids.add(str(did))
    doc_meta: dict[str, KnowledgeDocumentRow] = {}
    if doc_ids:
        rows = (await session.execute(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id.in_(doc_ids)))).scalars().all()
        doc_meta = {r.id: r for r in rows}
    for case in result.get("cases") or []:
        for item in case.get("items") or []:
            row = doc_meta.get(str(item.get("doc_id") or ""))
            if row is None:
                continue
            item["doc_title"] = row.title
            item["source_filename"] = row.source_filename
            if not item.get("title"):
                item["title"] = row.title

    return RecallEvalResponse(
        top_k=result["top_k"],
        case_count=result["case_count"],
        needle_hit_rate=float(result["needle_hit_rate"]),
        precision_at_k=result.get("precision_at_k"),
        recall_at_k=result.get("recall_at_k"),
        labeled_case_count=int(result.get("labeled_case_count") or 0),
        cases=list(result.get("cases") or []),
        trace_id=str(uuid.uuid4()),
    )


def _attach_user_attrs(items: list[EvidenceItem]) -> None:
    from deerflow.knowledge.rag import user_attrs_from_metadata

    for it in items:
        attrs = user_attrs_from_metadata(it.metadata)
        it.attrs = attrs or None


def _enrich_evidence_items(
    items: list[EvidenceItem],
    *,
    pack_id: str,
    space_ids: list[str],
    doc_meta: dict[str, KnowledgeDocumentRow],
) -> None:
    for it in items:
        it.metadata = dict(it.metadata or {})
        it.metadata.setdefault("scenario", pack_id)
        it.metadata.setdefault("spaces_searched", space_ids)
        row = doc_meta.get(str(it.metadata.get("doc_id") or ""))
        if row is None:
            continue
        it.metadata["source_filename"] = row.source_filename
        it.metadata["doc_title"] = row.title
        if row.effective_from is not None:
            it.metadata["effective_from"] = row.effective_from.isoformat()
        if row.effective_to is not None:
            it.metadata["effective_to"] = row.effective_to.isoformat()
        attrs = row.attrs if isinstance(row.attrs, dict) else {}
        for key, value in attrs.items():
            if key.startswith("_"):
                continue
            it.metadata.setdefault(key, value)
        if not it.title:
            it.title = row.title
        if not it.citable_as:
            heading = it.metadata.get("heading_path")
            article = it.metadata.get("article_no")
            base = f"{row.title} / {article}".strip(" /") if article else row.title
            it.citable_as = f"{base} / {heading}".strip(" /") if heading else base


async def search(
    session: AsyncSession,
    *,
    user_id: str,
    system_role: str,
    query: str,
    spaces: list[str] | None,
    top_k: int | None,
    retrieve_top_k: int | None = None,
    similarity_cutoff: float | None = None,
    knowledge_version: str = "current",
    scenario: str | None = None,
    as_of_date: str | None = None,
    fusion_queries: int | None = None,
) -> EvidencePackResponse:
    from fastapi import HTTPException

    if not query.strip():
        raise HTTPException(status_code=422, detail="query required")

    spaces, scenario = resolve_agent_knowledge_scope(spaces, scenario)
    accessible = await list_accessible_spaces(session, user_id=user_id, system_role=system_role)
    allowed_ids = {s.id for s in accessible}
    accessible_by_id = {s.id: s for s in accessible}
    space_ids = _resolve_search_space_ids(spaces, allowed_ids)

    trace_id = str(uuid.uuid4())
    if not space_ids:
        return EvidencePackResponse(
            knowledge_version=knowledge_version,
            trace_id=trace_id,
            items=[],
            answer=None,
        )

    default_scenarios: list[str] = []
    for sid in space_ids:
        sp = accessible_by_id.get(sid)
        if sp and sp.default_scenarios:
            default_scenarios = list(sp.default_scenarios)
            break
    pack = resolve_scenario(request_scenario=scenario, space_default_scenarios=default_scenarios)
    scenario_cfg = get_scenario_config(pack.id)
    space_top_k: int | None = None
    space_score: float | None = None
    if space_ids:
        primary = accessible_by_id.get(space_ids[0])
        if primary is not None:
            space_top_k, space_score = space_retrieval_from_row(primary)
    effective_top_k = top_k if top_k is not None else space_top_k if space_top_k is not None else pack.top_k
    final_top_k = int(effective_top_k or scenario_cfg.top_k or 8)
    pool_k = retrieve_top_k if retrieve_top_k is not None else effective_top_k
    per_space_pool = max(1, int(pool_k or final_top_k))
    cutoff = similarity_cutoff if similarity_cutoff is not None else (space_score if space_score is not None else pack.score)
    if fusion_queries is None and scenario_cfg.fusion_num_queries is not None:
        fusion_queries = max(1, int(scenario_cfg.fusion_num_queries))

    ver_label = (knowledge_version or "current").strip() or "current"
    release_by_space = {sid: space_knowledge_version(accessible_by_id.get(sid)) if ver_label == "current" else ver_label for sid in space_ids}
    resolved_version = ver_label if ver_label != "current" else next(iter(release_by_space.values()), "current")
    merge_mode = str(scenario_cfg.merge_mode or "slot_then_rrf")

    async def _search_one(space_id: str) -> tuple[str, list[dict]]:
        release = release_by_space.get(space_id, "current")
        items = await asyncio.to_thread(
            search_one_space,
            space_id=space_id,
            query=query,
            top_k=per_space_pool,
            similarity_cutoff=cutoff,
            release=release,
            fusion_queries=fusion_queries,
            merge_mode=merge_mode,
        )
        return space_id, items

    if len(space_ids) == 1:
        _sid, raw = await _search_one(space_ids[0])
        space_results = [{"space_id": _sid, "hit_count": len(raw)}]
    else:
        pairs = await asyncio.gather(*[_search_one(sid) for sid in space_ids])
        budgets = space_budgets(len(space_ids), final_top_k)
        buckets = [(sid, items, budget) for (sid, items), budget in zip(pairs, budgets)]
        raw = merge_space_hits(buckets, final_top_k=final_top_k, merge_mode=merge_mode)
        space_results = [{"space_id": sid, "hit_count": len(items)} for sid, items in pairs]

    as_of_dt = parse_as_of(as_of_date)
    raw = rank_by_temporal(raw, query=query, as_of=as_of_dt)
    raw = stable_rank_items(raw)[:final_top_k]

    doc_ids = {str(x.get("metadata", {}).get("doc_id")) for x in raw if x.get("metadata", {}).get("doc_id")}
    doc_meta: dict[str, KnowledgeDocumentRow] = {}
    if doc_ids:
        rows = (await session.execute(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id.in_(doc_ids)))).scalars().all()
        doc_meta = {r.id: r for r in rows}
    items = [EvidenceItem.model_validate(x) for x in raw]
    _enrich_evidence_items(
        items,
        pack_id=pack.id,
        space_ids=space_ids,
        doc_meta=doc_meta,
    )
    _attach_user_attrs(items)
    extra: dict[str, Any] = {}
    if len(space_ids) > 1:
        extra["metadata"] = {
            "spaces": list(space_ids),
            "merge_mode": merge_mode,
            "space_results": space_results,
        }
    return EvidencePackResponse(
        knowledge_version=resolved_version,
        trace_id=trace_id,
        items=items,
        **extra,
    )
