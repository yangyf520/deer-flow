"""Knowledge Gateway API: /api/knowledge/v1"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from app.gateway.authz import require_auth, require_permission
from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.knowledge import service as knowledge_service
from deerflow.knowledge.rag import scenario_kind_ids
from deerflow.knowledge.service import (
    DocumentChunksResponse,
    DocumentImportResponse,
    DocumentResponse,
    DocumentsListResponse,
    DocumentUpdateRequest,
    EvidencePackResponse,
    KindsListResponse,
    KnowledgeSearchRequest,
    RecallEvalRequest,
    RecallEvalResponse,
    ScenarioPackResponse,
    ScenariosListResponse,
    SpaceCreateRequest,
    SpaceGrantRequest,
    SpaceGrantResponse,
    SpaceGrantsListResponse,
    SpaceResponse,
    SpacesListResponse,
    SpaceUpdateRequest,
    docling_extra_available,
    knowledge_extra_available,
    list_configured_kinds,
    require_knowledge_extra,
)
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.knowledge.model import KnowledgeDocumentRow

router = APIRouter(prefix="/api/knowledge/v1", tags=["knowledge"])


def _session_factory():
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    return factory


def _user(request: Request):
    auth = getattr(request.state, "auth", None)
    if auth is None or auth.user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return auth.user


def _uid(user) -> str:
    """User.id is a UUID in the auth model; knowledge tables store strings."""
    return str(user.id)


@router.get("/health")
async def knowledge_health() -> dict:
    return {
        "enabled": get_knowledge_config().enabled,
        "extra_installed": knowledge_extra_available(),
        "docling_installed": docling_extra_available(),
        "parse": "docling",
    }


@router.get("/scenarios", response_model=ScenariosListResponse)
@require_auth
@require_permission("knowledge", "read")
async def list_scenarios(request: Request) -> ScenariosListResponse:
    """List Scenario Packs from config.yaml (type / top_k / score / lane kinds)."""
    items = [
        ScenarioPackResponse(
            description=s.description,
            type=s.type,
            top_k=s.top_k,
            score=s.effective_score,
            kinds=scenario_kind_ids(s),
        )
        for s in get_knowledge_config().scenarios
    ]
    return ScenariosListResponse(items=items, total=len(items))


@router.get("/kinds", response_model=KindsListResponse)
@require_auth
@require_permission("knowledge", "read")
async def list_kinds(request: Request) -> KindsListResponse:
    """Document kind ids from config (display labels are frontend i18n)."""
    items = list_configured_kinds()
    return KindsListResponse(items=items, total=len(items))


@router.post("/spaces", response_model=SpaceResponse, status_code=201)
@require_auth
@require_permission("knowledge", "write")
async def create_space(body: SpaceCreateRequest, request: Request) -> SpaceResponse:
    user = _user(request)
    if not get_knowledge_config().authz.allow_user_create_space and user.system_role != "admin":
        raise HTTPException(status_code=403, detail="Creating spaces is disabled")
    factory = _session_factory()
    async with factory() as session:
        return await knowledge_service.create_space(
            session,
            user_id=_uid(user),
            space_id=body.id,
            name=body.name,
            description=body.description,
            access=body.access,
            allowed_kinds=body.allowed_kinds,
            scenario=body.scenario,
            default_scenarios=body.default_scenarios,
        )


@router.get("/spaces/me", response_model=SpacesListResponse)
@require_auth
@require_permission("knowledge", "read")
async def list_my_spaces(request: Request) -> SpacesListResponse:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        items = await knowledge_service.list_accessible_spaces(session, user_id=_uid(user), system_role=user.system_role)
    return SpacesListResponse(items=items, total=len(items))


@router.get("/spaces/{space_id}", response_model=SpaceResponse)
@require_auth
@require_permission("knowledge", "read")
async def get_space(space_id: str, request: Request) -> SpaceResponse:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        space, role = await knowledge_service.get_space_or_404(session, space_id=space_id, user_id=_uid(user), system_role=user.system_role)
        return knowledge_service.space_to_response(space, my_role=role)


@router.patch("/spaces/{space_id}", response_model=SpaceResponse)
@require_auth
@require_permission("knowledge", "write")
async def update_space(space_id: str, body: SpaceUpdateRequest, request: Request) -> SpaceResponse:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        space, _ = await knowledge_service.get_space_or_404(session, space_id=space_id, user_id=_uid(user), system_role=user.system_role, min_role="admin")
        if body.name is not None:
            space.name = body.name
        if body.description is not None:
            space.description = body.description
        if body.access is not None:
            space.access = body.access
        if body.scenario is not None or body.default_scenarios is not None:
            bound = knowledge_service._resolve_bound_scenario(body.scenario, body.default_scenarios)
            space.default_scenarios = [bound]
            if body.allowed_kinds is not None:
                space.allowed_kinds = knowledge_service.allowed_kinds_for_scenario(bound, body.allowed_kinds)
            else:
                # Re-bind scenario → sync whitelist to that scenario's lanes.
                space.allowed_kinds = knowledge_service.allowed_kinds_for_scenario(bound, None)
        elif body.allowed_kinds is not None:
            bound = knowledge_service._resolve_bound_scenario(None, list(space.default_scenarios or []))
            space.allowed_kinds = knowledge_service.allowed_kinds_for_scenario(bound, body.allowed_kinds)
        if body.knowledge_version is not None:
            knowledge_service.set_space_knowledge_version(space, body.knowledge_version)
        await session.commit()
        await session.refresh(space)
        role = "admin"
        return knowledge_service.space_to_response(space, my_role=role)


@router.delete("/spaces/{space_id}", status_code=204)
@require_auth
@require_permission("knowledge", "write")
async def delete_space(space_id: str, request: Request) -> None:
    # No require_knowledge_extra: DB delete must work without LlamaIndex extra.
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.delete_space(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
        )


@router.get("/spaces/{space_id}/grants", response_model=SpaceGrantsListResponse)
@require_auth
@require_permission("knowledge", "read")
async def get_grants(space_id: str, request: Request) -> SpaceGrantsListResponse:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            min_role="admin",
        )
        items = await knowledge_service.list_grants(session, space_id)
    return SpaceGrantsListResponse(items=items, total=len(items))


@router.put("/spaces/{space_id}/grants", response_model=SpaceGrantResponse)
@require_auth
@require_permission("knowledge", "write")
async def put_grant(
    space_id: str,
    body: SpaceGrantRequest,
    request: Request,
) -> SpaceGrantResponse:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            min_role="admin",
        )
        return await knowledge_service.upsert_grant(
            session,
            space_id=space_id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            role=body.role,
            granted_by=_uid(user),
        )


@router.delete(
    "/spaces/{space_id}/grants/{subject_type}/{subject_id}",
    status_code=204,
)
@require_auth
@require_permission("knowledge", "write")
async def remove_grant(
    space_id: str,
    subject_type: str,
    subject_id: str,
    request: Request,
) -> None:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            min_role="admin",
        )
        await knowledge_service.delete_grant(
            session,
            space_id=space_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )


@router.post("/spaces/{space_id}/documents/import", response_model=DocumentImportResponse, status_code=201)
@require_auth
@require_permission("knowledge", "write")
async def import_document(
    space_id: str,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    kind: str = Form(...),
    tags: Annotated[list[str], Form()] = [],
) -> DocumentImportResponse:
    require_knowledge_extra()
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(session, space_id=space_id, user_id=_uid(user), system_role=user.system_role, min_role="editor")
    data = await file.read()
    return await knowledge_service.import_document(
        factory,
        space_id=space_id,
        user_id=_uid(user),
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        title=title,
        kind=kind,
        tags=tags or None,
    )


@router.get("/spaces/{space_id}/documents", response_model=DocumentsListResponse)
@require_auth
@require_permission("knowledge", "read")
async def list_documents(
    space_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    kind: str | None = Query(None, description="Filter by document kind id"),
    q: str | None = Query(None, description="Filter by title or filename (case-insensitive substring)"),
) -> DocumentsListResponse:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(session, space_id=space_id, user_id=_uid(user), system_role=user.system_role)
        items, total = await knowledge_service.list_documents(session, space_id, kind=kind, q=q, limit=limit, offset=offset)
    return DocumentsListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/spaces/{space_id}/documents/{doc_id}", response_model=DocumentResponse)
@require_auth
@require_permission("knowledge", "read")
async def get_document(space_id: str, doc_id: str, request: Request) -> DocumentResponse:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(session, space_id=space_id, user_id=_uid(user), system_role=user.system_role)
        row = await session.get(KnowledgeDocumentRow, doc_id)
        if row is None or row.space_id != space_id:
            raise HTTPException(status_code=404, detail="Document not found")
        names = await knowledge_service.resolve_user_display_names(session, [row.created_by])
        return knowledge_service.doc_to_response(row, created_by_name=names.get(row.created_by))


@router.patch("/spaces/{space_id}/documents/{doc_id}", response_model=DocumentResponse)
@require_auth
@require_permission("knowledge", "write")
async def patch_document(
    space_id: str,
    doc_id: str,
    body: DocumentUpdateRequest,
    request: Request,
) -> DocumentResponse:
    require_knowledge_extra()
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            min_role="editor",
        )
        return await knowledge_service.update_document(
            session,
            space_id=space_id,
            doc_id=doc_id,
            kind=body.kind,
            tags=body.tags,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
            title=body.title,
        )


@router.get("/spaces/{space_id}/documents/{doc_id}/chunks", response_model=DocumentChunksResponse)
@require_auth
@require_permission("knowledge", "read")
async def list_document_chunks(space_id: str, doc_id: str, request: Request) -> DocumentChunksResponse:
    """Inspect ingest leaf chunks for maintenance (from LlamaIndex docstore)."""
    require_knowledge_extra()
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(session, space_id=space_id, user_id=_uid(user), system_role=user.system_role)
        return await knowledge_service.get_document_chunks(session, space_id=space_id, doc_id=doc_id)


@router.delete("/spaces/{space_id}/documents/{doc_id}", status_code=204)
@require_auth
@require_permission("knowledge", "write")
async def delete_document(space_id: str, doc_id: str, request: Request) -> None:
    # No require_knowledge_extra: DB row delete must work without LlamaIndex extra;
    # vector cleanup in service is already best-effort.
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            min_role="editor",
        )
        await knowledge_service.delete_document(session, space_id=space_id, doc_id=doc_id)


@router.post("/spaces/{space_id}/documents/{doc_id}/reindex", response_model=DocumentImportResponse)
@require_auth
@require_permission("knowledge", "write")
async def reindex_document(
    space_id: str,
    doc_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> DocumentImportResponse:
    """Re-parse and re-embed from an uploaded file."""
    require_knowledge_extra()
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            min_role="editor",
        )
    data = await file.read()
    doc = await knowledge_service.reindex_document(
        factory,
        space_id=space_id,
        doc_id=doc_id,
        data=data,
        filename=file.filename,
        content_type=file.content_type,
    )
    return DocumentImportResponse(doc_id=doc.id, status=doc.status, job_phase=doc.job_phase, progress=doc.progress)


@router.post("/search", response_model=EvidencePackResponse)
@require_auth
@require_permission("knowledge", "read")
async def search(body: KnowledgeSearchRequest, request: Request) -> EvidencePackResponse:
    require_knowledge_extra()
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        return await knowledge_service.search(
            session,
            user_id=_uid(user),
            system_role=user.system_role,
            query=body.query,
            spaces=body.spaces,
            kinds=body.kinds,
            tags=body.tags,
            top_k=body.top_k,
            knowledge_version=body.knowledge_version,
            scenario=body.scenario,
        )


@router.post("/eval/recall", response_model=RecallEvalResponse)
@require_auth
@require_permission("knowledge", "read")
async def eval_recall(body: RecallEvalRequest, request: Request) -> RecallEvalResponse:
    """Offline-style retrieval eval: Precision@k / Recall@k / needle hit rate."""
    require_knowledge_extra()
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        return await knowledge_service.eval_recall(
            session,
            user_id=_uid(user),
            system_role=user.system_role,
            spaces=body.spaces,
            cases=body.cases,
            top_k=body.top_k,
        )
