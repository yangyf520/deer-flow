"""Knowledge Gateway API: /api/v1/knowledge"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from app.gateway.authz import require_auth, require_permission
from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.knowledge import service as knowledge_service
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
    require_knowledge_extra,
)
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.knowledge.model import KnowledgeDocumentRow

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


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


def _request_locale(request: Request) -> str:
    from deerflow.knowledge.catalog import locale_from_header, norm_locale

    query = request.query_params.get("locale")
    if query:
        return norm_locale(query)
    return locale_from_header(request.headers.get("Accept-Language"))


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
    """List knowledge scenarios from DB code table (pub_codes)."""
    locale = _request_locale(request)
    factory = _session_factory()
    async with factory() as session:
        catalog = await knowledge_service.get_knowledge_catalog_from_db(session, locale=locale)
    return ScenariosListResponse(items=catalog.scenarios, total=len(catalog.scenarios))


@router.get("/catalog", response_model=knowledge_service.KnowledgeCatalogResponse)
@require_auth
@require_permission("knowledge", "read")
async def list_catalog(request: Request) -> knowledge_service.KnowledgeCatalogResponse:
    """Knowledge code catalog from DB (pub_codes): scenarios, kinds, tags, tag_groups."""
    locale = _request_locale(request)
    factory = _session_factory()
    async with factory() as session:
        return await knowledge_service.get_knowledge_catalog_from_db(session, locale=locale)


@router.post("/catalog/migrate-host", response_model=knowledge_service.MigrateCatalogHostResponse)
@require_auth
@require_permission("knowledge", "write")
async def migrate_catalog_host(
    body: knowledge_service.MigrateCatalogHostRequest,
    request: Request,
) -> knowledge_service.MigrateCatalogHostResponse:
    """Move all catalog scenarios to another knowledge space (码表归属迁移)."""
    factory = _session_factory()
    async with factory() as session:
        from deerflow.knowledge.catalog import migrate_catalog_host as migrate_host

        updated = await migrate_host(session, host_space_id=body.host_space_id)
    return knowledge_service.MigrateCatalogHostResponse(
        host_space_id=body.host_space_id.strip(),
        updated=updated,
    )


@router.get("/kinds", response_model=KindsListResponse)
@require_auth
@require_permission("knowledge", "read")
async def list_kinds(request: Request) -> KindsListResponse:
    """Document kinds from DB catalog."""
    locale = _request_locale(request)
    factory = _session_factory()
    async with factory() as session:
        catalog = await knowledge_service.get_knowledge_catalog_from_db(session, locale=locale)
    return KindsListResponse(items=catalog.kinds, total=len(catalog.kinds))


@router.put("/scenarios/{code}", response_model=ScenarioPackResponse)
@require_auth
@require_permission("knowledge", "write")
async def upsert_scenario(code: str, body: knowledge_service.ScenarioDefinitionRequest, request: Request) -> ScenarioPackResponse:
    """Create or update a knowledge scenario (code + label + retrieval profile)."""
    user = _user(request)
    if body.code != code:
        raise HTTPException(status_code=422, detail="scenario code in path and body must match")
    factory = _session_factory()
    async with factory() as session:
        from deerflow.knowledge.catalog import upsert_scenario

        await upsert_scenario(
            session,
            code=body.code,
            label=body.label,
            locale=_request_locale(request),
            labels=body.labels,
            description=body.description,
            merge_mode=body.merge_mode,
            fusion_num_queries=body.fusion_num_queries,
            host_space_id=body.host_space_id,
            created_by=_uid(user),
        )
        await knowledge_service.ensure_catalog_scenario_space(
            session,
            user_id=_uid(user),
            scenario_code=body.code,
            label=body.label,
        )
        catalog = await knowledge_service.get_knowledge_catalog_from_db(session, locale=_request_locale(request))
    pack = next((s for s in catalog.scenarios if s.type == code), None)
    if pack is None:
        raise HTTPException(status_code=500, detail="scenario upsert failed")
    return pack


@router.delete("/scenarios/{code}", status_code=204)
@require_auth
@require_permission("knowledge", "write")
async def delete_scenario(code: str, request: Request) -> None:
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        deleted = await knowledge_service.delete_scenario_cascade(
            session,
            user_id=_uid(user),
            system_role=user.system_role,
            code=code,
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="Scenario not found")


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
            top_k=body.top_k,
            score=body.score,
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
        return await knowledge_service.update_space(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            body=body,
        )


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


@router.post("/spaces/{space_id}/documents", response_model=DocumentImportResponse, status_code=201)
@require_auth
@require_permission("knowledge", "write")
async def import_document(
    space_id: str,
    request: Request,
    file: UploadFile | None = File(None),
    title: str | None = Form(None),
    kind: str = Form(...),
    tags: Annotated[list[str], Form()] = [],
    attrs: str | None = Form(None, description="JSON object of document-level custom metadata"),
    segments: str | None = Form(
        None,
        description='JSON array of {"text":"...", "metadata": {...}} for pre-chunked rows (e.g. row_no)',
    ),
) -> DocumentImportResponse:
    """Import a file or structured segments into a knowledge space (parse, chunk, embed)."""
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
    parsed_attrs = knowledge_service.parse_embed_attrs_json(attrs)
    parsed_segments = knowledge_service.parse_embed_segments_json(segments)
    data = b""
    filename = "segments.json"
    if file is not None:
        data = await file.read()
        filename = file.filename or "upload.bin"
    if not data and parsed_segments is None:
        raise HTTPException(status_code=400, detail="file or segments required")
    return await knowledge_service.import_document(
        factory,
        space_id=space_id,
        user_id=_uid(user),
        filename=filename,
        content_type=file.content_type if file is not None else "application/json",
        data=data,
        title=title,
        kind=kind,
        tags=tags or None,
        attrs=parsed_attrs or None,
        segments=parsed_segments,
    )


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
            attrs=body.attrs,
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


@router.delete("/spaces/{space_id}/documents", status_code=204)
@require_auth
@require_permission("knowledge", "write")
async def delete_all_documents(space_id: str, request: Request) -> None:
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
        await knowledge_service.delete_all_documents(session, space_id=space_id)


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


@router.post("/search", response_model=EvidencePackResponse, response_model_exclude_none=True)
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
