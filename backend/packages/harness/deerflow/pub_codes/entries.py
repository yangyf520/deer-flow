"""CRUD for flat pub_codes entries in a domain category."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.persistence.pub_codes.model import PubCodeRow
from deerflow.pub_codes.bundle import KNOWLEDGE_DOMAIN
from deerflow.pub_codes.domains import CODE_CATEGORY


def _norm_str_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


async def upsert_flat_entry(
    session: AsyncSession,
    *,
    domain: str,
    type_key: str,
    code: str,
    label: str,
    attrs: dict[str, Any] | None = None,
    parent_code: str = "",
) -> PubCodeRow:
    did = (domain or "").strip().lower()
    entry_type = (type_key or "").strip()
    cid = (code or "").strip()
    parent = (parent_code or "").strip()
    display = (label or "").strip() or cid
    if not did or not entry_type or not cid:
        raise HTTPException(status_code=422, detail="domain, type_key and code are required")
    if cid == CODE_CATEGORY:
        raise HTTPException(status_code=422, detail="invalid entry code")

    if parent:
        parent_row = (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == did,
                    PubCodeRow.type_key == entry_type,
                    PubCodeRow.parent_code == "",
                    PubCodeRow.code == parent,
                )
            )
        ).scalar_one_or_none()
        if parent_row is None or parent_row.code == CODE_CATEGORY:
            raise HTTPException(status_code=404, detail="parent category not found")

    row = (
        await session.execute(
            select(PubCodeRow).where(
                PubCodeRow.domain == did,
                PubCodeRow.type_key == entry_type,
                PubCodeRow.parent_code == parent,
                PubCodeRow.code == cid,
            )
        )
    ).scalar_one_or_none()

    next_attrs = dict(row.attrs or {}) if row is not None else {}
    if attrs is not None:
        for key, value in attrs.items():
            if isinstance(value, list):
                next_attrs[key] = _norm_str_list([str(v) for v in value])
            elif value is None:
                next_attrs.pop(key, None)
            else:
                next_attrs[key] = value

    now = datetime.now(UTC)
    if row is None:
        max_sort = (
            (
                await session.execute(
                    select(PubCodeRow.sort_order).where(
                        PubCodeRow.domain == did,
                        PubCodeRow.type_key == entry_type,
                        PubCodeRow.parent_code == parent,
                        PubCodeRow.code != CODE_CATEGORY,
                    )
                )
            )
            .scalars()
            .all()
        )
        sort_order = max((int(v or 0) for v in max_sort), default=-1) + 1
        row = PubCodeRow(
            id=str(uuid.uuid4()),
            domain=did,
            type_key=entry_type,
            code=cid,
            label=display,
            parent_code=parent,
            attrs=next_attrs,
            sort_order=sort_order,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.label = display
        row.attrs = next_attrs
        row.updated_at = now

    await session.commit()
    if did == KNOWLEDGE_DOMAIN:
        from deerflow.knowledge.app.codes import refresh_cache

        await refresh_cache(session)
    return row


async def delete_flat_entry(
    session: AsyncSession,
    *,
    domain: str,
    type_key: str,
    code: str,
    parent_code: str = "",
) -> bool:
    did = (domain or "").strip().lower()
    entry_type = (type_key or "").strip()
    cid = (code or "").strip()
    parent = (parent_code or "").strip()
    if not did or not entry_type or not cid:
        return False

    row = (
        await session.execute(
            select(PubCodeRow).where(
                PubCodeRow.domain == did,
                PubCodeRow.type_key == entry_type,
                PubCodeRow.parent_code == parent,
                PubCodeRow.code == cid,
            )
        )
    ).scalar_one_or_none()
    if row is None or row.code == CODE_CATEGORY:
        return False

    if not parent:
        children = list(
            (
                await session.execute(
                    select(PubCodeRow).where(
                        PubCodeRow.domain == did,
                        PubCodeRow.type_key == entry_type,
                        PubCodeRow.parent_code == cid,
                    )
                )
            )
            .scalars()
            .all()
        )
        for child in children:
            await session.delete(child)

    await session.delete(row)
    await session.commit()
    if did == KNOWLEDGE_DOMAIN:
        from deerflow.knowledge.app.codes import refresh_cache

        await refresh_cache(session)
    return True
