"""Code-table domain registry and bulk operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.persistence.pub_codes.model import PubCodeRow
from deerflow.pub_codes.bundle import KNOWLEDGE_DOMAIN

REGISTERED_DOMAINS: tuple[str, ...] = (KNOWLEDGE_DOMAIN,)
CODE_CATEGORY = "_category"
DEFAULT_KNOWLEDGE_TYPE_KEY = "industry_tag"
DEFAULT_FLAT_TYPE_KEY = "entry"
REGISTERED_CATEGORIES: tuple[tuple[str, str], ...] = ((KNOWLEDGE_DOMAIN, DEFAULT_KNOWLEDGE_TYPE_KEY),)


def _hierarchy_counts(domain_rows: list[PubCodeRow]) -> tuple[int, int]:
    parent_count = 0
    child_count = 0
    for row in domain_rows:
        if row.code == CODE_CATEGORY:
            continue
        if (row.parent_code or "").strip():
            child_count += 1
        else:
            parent_count += 1
    return parent_count, child_count


def _primary_root(domain_rows: list[PubCodeRow]) -> PubCodeRow | None:
    roots = [row for row in domain_rows if row.code != CODE_CATEGORY and not (row.parent_code or "").strip()]
    return roots[0] if roots else None


async def list_domain_summaries(session: AsyncSession) -> list[dict[str, int | str]]:
    rows = list((await session.execute(select(PubCodeRow).where(PubCodeRow.enabled.is_(True)).order_by(PubCodeRow.sort_order))).scalars().all())
    meta_by_key = {(str(row.domain), str(row.type_key)): row for row in rows if row.code == CODE_CATEGORY}
    by_domain: dict[str, list[PubCodeRow]] = {}
    for row in rows:
        by_domain.setdefault(str(row.domain), []).append(row)

    items: list[dict[str, int | str]] = []
    seen_domains: set[str] = set()

    for domain, type_key in REGISTERED_CATEGORIES:
        domain_rows = by_domain.get(domain, [])
        meta = meta_by_key.get((domain, type_key))
        entry_count = sum(1 for row in domain_rows if row.code != CODE_CATEGORY)
        items.append(
            {
                "domain": domain,
                "type_key": type_key,
                "label": str(meta.label or "") if meta is not None else "",
                "parent_code": "",
                "entry_count": entry_count,
            }
        )
        seen_domains.add(domain)

    for domain in sorted(by_domain):
        if domain in seen_domains:
            continue
        domain_rows = by_domain[domain]
        _, child_count = _hierarchy_counts(domain_rows)
        primary = _primary_root(domain_rows)
        meta = next((row for row in domain_rows if row.code == CODE_CATEGORY), None)
        type_key = str(primary.type_key) if primary is not None else str(meta.type_key) if meta is not None else DEFAULT_FLAT_TYPE_KEY
        items.append(
            {
                "domain": domain,
                "type_key": type_key,
                "label": str(primary.label or "") if primary is not None else "",
                "parent_code": str(primary.code) if primary is not None else "",
                "entry_count": child_count,
            }
        )
    return items


async def register_domain(
    session: AsyncSession,
    *,
    domain: str,
    code: str,
    label: str = "",
    type_key: str = "",
    attrs: dict[str, Any] | None = None,
) -> PubCodeRow:
    from fastapi import HTTPException

    from deerflow.pub_codes.entries import upsert_flat_entry

    did = (domain or "").strip().lower()
    cid = (code or "").strip()
    entry_type = (type_key or DEFAULT_FLAT_TYPE_KEY).strip()
    display = (label or "").strip()
    if not did:
        raise HTTPException(status_code=422, detail="domain is required")
    if not cid:
        raise HTTPException(status_code=422, detail="code is required")
    if cid == CODE_CATEGORY:
        raise HTTPException(status_code=422, detail="invalid code")
    if entry_type == CODE_CATEGORY:
        raise HTTPException(status_code=422, detail="invalid type_key")
    if did in REGISTERED_DOMAINS:
        raise HTTPException(status_code=409, detail="domain is reserved")

    existing = (await session.execute(select(PubCodeRow).where(PubCodeRow.domain == did).limit(1))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="domain already exists")

    return await upsert_flat_entry(
        session,
        domain=did,
        type_key=entry_type,
        code=cid,
        label=display or cid,
        parent_code="",
        attrs=attrs,
    )


async def update_domain_meta(
    session: AsyncSession,
    *,
    domain: str,
    type_key: str,
    label: str,
    new_type_key: str = "",
) -> PubCodeRow:
    import uuid
    from datetime import UTC, datetime

    from fastapi import HTTPException

    did = (domain or "").strip().lower()
    entry_type = (type_key or "").strip()
    next_type = (new_type_key or "").strip() or entry_type
    display = (label or "").strip()
    if not did or not entry_type:
        raise HTTPException(status_code=422, detail="domain and type_key are required")
    if not display:
        raise HTTPException(status_code=422, detail="label is required")
    if not next_type:
        raise HTTPException(status_code=422, detail="type_key is required")
    if next_type != entry_type and (did, entry_type) in REGISTERED_CATEGORIES:
        raise HTTPException(status_code=409, detail="built-in category type_key cannot change")

    row = (
        await session.execute(
            select(PubCodeRow).where(
                PubCodeRow.domain == did,
                PubCodeRow.type_key == entry_type,
                PubCodeRow.code == CODE_CATEGORY,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        if (did, entry_type) not in REGISTERED_CATEGORIES:
            raise HTTPException(status_code=404, detail="domain category not found")
        row = PubCodeRow(
            id=str(uuid.uuid4()),
            domain=did,
            type_key=entry_type,
            code=CODE_CATEGORY,
            label=display,
            parent_code="",
            attrs={},
            sort_order=0,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.label = display
        if next_type != entry_type:
            in_use = (
                await session.scalar(
                    select(func.count())
                    .select_from(PubCodeRow)
                    .where(
                        PubCodeRow.domain == did,
                        PubCodeRow.type_key == entry_type,
                        PubCodeRow.code != CODE_CATEGORY,
                        PubCodeRow.enabled.is_(True),
                    )
                )
            ) or 0
            if in_use > 0:
                raise HTTPException(
                    status_code=409,
                    detail="type_key cannot change while entries exist",
                )
            row.type_key = next_type
        row.updated_at = now
    await session.commit()
    return row


async def delete_domain_rows(session: AsyncSession, *, domain: str) -> int:
    did = (domain or "").strip().lower()
    if not did:
        return 0
    rows = list((await session.execute(select(PubCodeRow).where(PubCodeRow.domain == did))).scalars().all())
    if not rows:
        return 0
    for row in rows:
        await session.delete(row)
    await session.commit()
    if did == KNOWLEDGE_DOMAIN:
        from deerflow.knowledge.app.codes import refresh_cache

        await refresh_cache(session)
    return len(rows)
