"""Code-table domain registry and bulk operations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.persistence.pub_codes.model import PubCodeRow
from deerflow.pub_codes.bundle import KNOWLEDGE_DOMAIN

REGISTERED_DOMAINS: tuple[str, ...] = (KNOWLEDGE_DOMAIN,)
CODE_CATEGORY = "_category"
DEFAULT_KNOWLEDGE_TYPE_KEY = "industry_tag"
REGISTERED_CATEGORIES: tuple[tuple[str, str], ...] = ((KNOWLEDGE_DOMAIN, DEFAULT_KNOWLEDGE_TYPE_KEY),)


async def list_domain_summaries(session: AsyncSession) -> list[dict[str, int | str]]:
    meta_rows = list(
        (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.enabled.is_(True),
                    PubCodeRow.code == CODE_CATEGORY,
                )
            )
        )
        .scalars()
        .all()
    )
    meta_by_key = {(str(row.domain), str(row.type_key)): row for row in meta_rows}
    counts = {
        (str(domain), str(type_key)): int(count)
        for domain, type_key, count in (
            await session.execute(
                select(PubCodeRow.domain, PubCodeRow.type_key, func.count())
                .where(
                    PubCodeRow.enabled.is_(True),
                    PubCodeRow.code != CODE_CATEGORY,
                )
                .group_by(PubCodeRow.domain, PubCodeRow.type_key)
            )
        ).all()
    }
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, int | str]] = []
    for domain, type_key in REGISTERED_CATEGORIES:
        meta = meta_by_key.get((domain, type_key))
        items.append(
            {
                "domain": domain,
                "type_key": type_key,
                "label": str(meta.label or "") if meta is not None else "",
                "entry_count": counts.get((domain, type_key), 0),
            }
        )
        seen.add((domain, type_key))
    for (domain, type_key), meta in sorted(meta_by_key.items()):
        if (domain, type_key) in seen:
            continue
        items.append(
            {
                "domain": domain,
                "type_key": type_key,
                "label": str(meta.label or ""),
                "entry_count": counts.get((domain, type_key), 0),
            }
        )
        seen.add((domain, type_key))
    return items


async def register_domain(
    session: AsyncSession,
    *,
    domain: str,
    type_key: str,
    label: str = "",
) -> PubCodeRow:
    import uuid
    from datetime import UTC, datetime

    from fastapi import HTTPException

    did = (domain or "").strip().lower()
    entry_type = (type_key or "").strip()
    display = (label or "").strip()
    if not did:
        raise HTTPException(status_code=422, detail="domain is required")
    if not entry_type:
        raise HTTPException(status_code=422, detail="type_key is required")
    if did in REGISTERED_DOMAINS:
        raise HTTPException(status_code=409, detail="domain is reserved")

    existing = (
        await session.execute(
            select(PubCodeRow).where(
                PubCodeRow.domain == did,
                PubCodeRow.type_key == entry_type,
                PubCodeRow.code == CODE_CATEGORY,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="domain category already exists")

    now = datetime.now(UTC)
    row = PubCodeRow(
        id=str(uuid.uuid4()),
        domain=did,
        type_key=entry_type,
        code=CODE_CATEGORY,
        label=display or f"{did}/{entry_type}",
        parent_code="",
        attrs={},
        sort_order=0,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    return row


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
