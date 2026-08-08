"""Knowledge API request/response models."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class SpaceCreateRequest(BaseModel):
    """Create a knowledge space.

    - ``name``: English machine-friendly display name (also used to derive id)
    - ``description``: Chinese / human-readable notes
    - ``id``: optional; auto-generated from ``name`` when omitted
    - ``scenario``: pub_codes scenario code to bind (retrieval profile)
    """

    name: str = Field(min_length=1, max_length=256, description="English name")
    description: str | None = Field(default=None, description="Chinese description / notes")
    id: str | None = Field(default=None, min_length=1, max_length=64, description="Optional; auto from name")
    access: str = "open"
    allowed_kinds: list[str] = Field(default_factory=list)
    scenario: str | None = Field(default=None, description="Bound pub_codes scenario code")
    top_k: int | None = Field(default=None, ge=1, le=50)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    # Legacy alias → normalized into scenario
    default_scenarios: list[str] = Field(default_factory=list)


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
    only_unassigned: bool = False


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
