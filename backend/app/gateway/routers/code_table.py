"""Generic code-table (pub_codes) Gateway API: /api/v1/code-table"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.gateway.authz import AuthContext, require_auth
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.pub_codes.model import PubCodeRow
from deerflow.pub_codes.bundle import KNOWLEDGE_DOMAIN, load_bundle
from deerflow.pub_codes.contract import (
    CodeTableDomainsListResponse,
    CodeTableDomainSummaryResponse,
    CreateCodeTableDomainRequest,
    DeleteCodeTableDomainResponse,
    PubCodeEntryResponse,
    UpdateCodeTableDomainRequest,
    UpdateCodeTableEntryRequest,
    UpsertCodeTableEntryRequest,
)
from deerflow.pub_codes.domains import (
    delete_domain_rows,
    list_domain_summaries,
    register_domain,
    update_domain_meta,
)
from deerflow.pub_codes.entries import delete_flat_entry, upsert_flat_entry

router = APIRouter(prefix="/api/v1/code-table", tags=["code-table"])


def _request_locale(request: Request) -> str:
    raw = (request.headers.get("accept-language") or "").split(",", 1)[0].strip()
    return raw or "zh-CN"


def _require_domain_write(request: Request, domain: str) -> None:
    did = domain.strip().lower()
    if did != KNOWLEDGE_DOMAIN:
        return
    auth: AuthContext = request.state.auth
    if not auth.has_permission("knowledge", "write"):
        raise HTTPException(status_code=403, detail="Permission denied: knowledge:write")


def _require_domain_read(request: Request, domain: str) -> None:
    did = domain.strip().lower()
    if did != KNOWLEDGE_DOMAIN:
        return
    auth: AuthContext = request.state.auth
    if not auth.has_permission("knowledge", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: knowledge:read")


@router.get("/bundle")
@require_auth
async def get_code_table_bundle(
    request: Request,
    domain: str = Query(..., min_length=1, description="Code-table domain, e.g. knowledge or legal"),
) -> Any:
    """Load a domain-specific code-table bundle.

    - ``knowledge``: structured scenarios, kinds, tags, and tag_groups (knowledge module view).
    - Other domains: flat ``pub_codes`` rows for that domain.
    """
    did = domain.strip().lower()
    _require_domain_read(request, did)
    factory = get_session_factory()
    async with factory() as session:
        return await load_bundle(session, domain=did, locale=_request_locale(request))


@router.get("/domains", response_model=CodeTableDomainsListResponse)
@require_auth
async def list_code_table_domains(request: Request) -> CodeTableDomainsListResponse:
    """Known code-table domains with entry counts."""
    _ = request
    factory = get_session_factory()
    async with factory() as session:
        summaries = await list_domain_summaries(session)
    items = [
        CodeTableDomainSummaryResponse(
            domain=str(row["domain"]),
            type_key=str(row.get("type_key") or ""),
            label=str(row.get("label") or ""),
            entry_count=int(row["entry_count"]),
        )
        for row in summaries
    ]
    return CodeTableDomainsListResponse(
        items=items,
        domains=[item.domain for item in items],
    )


@router.post("/domains", response_model=CodeTableDomainSummaryResponse, status_code=201)
@require_auth
async def create_code_table_domain(
    body: CreateCodeTableDomainRequest,
    request: Request,
) -> CodeTableDomainSummaryResponse:
    """Register a user-defined code-table domain."""
    _ = request
    domain = body.domain.strip().lower()
    type_key = body.type_key.strip()
    if domain != body.domain.strip().lower() or not domain.replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="invalid domain")
    if not type_key.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="invalid type_key")
    factory = get_session_factory()
    async with factory() as session:
        row = await register_domain(
            session,
            domain=domain,
            type_key=type_key,
            label=body.label.strip(),
        )
    return CodeTableDomainSummaryResponse(
        domain=row.domain,
        type_key=row.type_key,
        label=row.label or row.code,
        entry_count=0,
    )


@router.put("/domains/{domain}", response_model=CodeTableDomainSummaryResponse)
@require_auth
async def update_code_table_domain(
    domain: str,
    body: UpdateCodeTableDomainRequest,
    request: Request,
) -> CodeTableDomainSummaryResponse:
    """Update display metadata for a user-defined code-table domain."""
    _ = request
    did = domain.strip().lower()
    type_key = body.type_key.strip()
    new_type_key = body.new_type_key.strip()
    factory = get_session_factory()
    async with factory() as session:
        row = await update_domain_meta(
            session,
            domain=did,
            type_key=type_key,
            label=body.label.strip(),
            new_type_key=new_type_key,
        )
        summaries = await list_domain_summaries(session)
    saved_type_key = row.type_key
    summary = next(
        (item for item in summaries if str(item["domain"]) == did and str(item["type_key"]) == saved_type_key),
        None,
    )
    return CodeTableDomainSummaryResponse(
        domain=row.domain,
        type_key=saved_type_key,
        label=row.label or row.code,
        entry_count=int(summary["entry_count"]) if summary else 0,
    )


@router.delete("/domains/{domain}", response_model=DeleteCodeTableDomainResponse)
@require_auth
async def delete_code_table_domain(domain: str, request: Request) -> DeleteCodeTableDomainResponse:
    """Delete all pub_codes rows for a code-table domain."""
    did = domain.strip().lower()
    if not did:
        raise HTTPException(status_code=422, detail="domain is required")
    _require_domain_write(request, did)
    factory = get_session_factory()
    async with factory() as session:
        deleted = await delete_domain_rows(session, domain=did)
    return DeleteCodeTableDomainResponse(domain=did, deleted=deleted)


def _entry_response(row: PubCodeRow) -> PubCodeEntryResponse:
    return PubCodeEntryResponse(
        id=row.id,
        domain=row.domain,
        type_key=row.type_key,
        code=row.code,
        label=row.label or row.code,
        parent_code=row.parent_code or "",
        attrs=dict(row.attrs or {}) if isinstance(row.attrs, dict) else {},
        sort_order=int(row.sort_order or 0),
        enabled=bool(row.enabled),
    )


@router.post(
    "/domains/{domain}/entries",
    response_model=PubCodeEntryResponse,
    status_code=201,
)
@require_auth
async def create_code_table_entry(
    domain: str,
    body: UpsertCodeTableEntryRequest,
    request: Request,
) -> PubCodeEntryResponse:
    did = domain.strip().lower()
    _require_domain_write(request, did)
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == did,
                    PubCodeRow.type_key == body.type_key.strip(),
                    PubCodeRow.parent_code == "",
                    PubCodeRow.code == body.code.strip(),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="entry already exists")
        row = await upsert_flat_entry(
            session,
            domain=did,
            type_key=body.type_key.strip(),
            code=body.code.strip(),
            label=body.label.strip(),
            attrs=body.attrs,
        )
    return _entry_response(row)


@router.put("/domains/{domain}/entries/{code}", response_model=PubCodeEntryResponse)
@require_auth
async def update_code_table_entry(
    domain: str,
    code: str,
    body: UpdateCodeTableEntryRequest,
    request: Request,
) -> PubCodeEntryResponse:
    did = domain.strip().lower()
    _require_domain_write(request, did)
    factory = get_session_factory()
    async with factory() as session:
        row = await upsert_flat_entry(
            session,
            domain=did,
            type_key=body.type_key.strip(),
            code=code.strip(),
            label=body.label.strip(),
            attrs=body.attrs,
        )
    return _entry_response(row)


@router.delete("/domains/{domain}/entries/{code}", status_code=204)
@require_auth
async def delete_code_table_entry(
    domain: str,
    code: str,
    request: Request,
    type_key: str = Query(..., min_length=1),
) -> None:
    did = domain.strip().lower()
    _require_domain_write(request, did)
    factory = get_session_factory()
    async with factory() as session:
        deleted = await delete_flat_entry(
            session,
            domain=did,
            type_key=type_key.strip(),
            code=code.strip(),
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="entry not found")
