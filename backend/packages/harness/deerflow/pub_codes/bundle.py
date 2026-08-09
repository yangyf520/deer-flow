"""Load code-table bundles by domain."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.persistence.pub_codes.model import PubCodeRow
from deerflow.pub_codes.contract import CodeTableFlatBundleResponse, PubCodeEntryResponse

KNOWLEDGE_DOMAIN = "knowledge"
CODE_CATEGORY = "_category"


def _normalize_domain(domain: str) -> str:
    return (domain or "").strip().lower()


async def load_flat_bundle(session: AsyncSession, *, domain: str) -> CodeTableFlatBundleResponse:
    did = _normalize_domain(domain)
    if not did:
        raise HTTPException(status_code=422, detail="domain is required")
    rows = list(
        (
            await session.execute(
                select(PubCodeRow)
                .where(
                    PubCodeRow.domain == did,
                    PubCodeRow.enabled.is_(True),
                    PubCodeRow.code != CODE_CATEGORY,
                )
                .order_by(PubCodeRow.type_key, PubCodeRow.sort_order, PubCodeRow.code)
            )
        )
        .scalars()
        .all()
    )
    items = [
        PubCodeEntryResponse(
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
        for row in rows
    ]
    return CodeTableFlatBundleResponse(domain=did, items=items)


async def load_bundle(session: AsyncSession, *, domain: str, locale: str = "zh-CN"):
    """Return a domain-specific bundle payload."""
    did = _normalize_domain(domain)
    if not did:
        raise HTTPException(status_code=422, detail="domain is required")
    if did == KNOWLEDGE_DOMAIN:
        from deerflow.knowledge.app import codes as kb_codes

        return await kb_codes.get_knowledge_catalog_from_db(session, locale=locale)
    return await load_flat_bundle(session, domain=did)
