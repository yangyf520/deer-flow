"""Knowledge spaces: ACL and CRUD."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.knowledge.adapters.storage import rename_space_vectors
from deerflow.knowledge.app.codes import rename_catalog_space_references, validate_scenario_code
from deerflow.knowledge.contract import (
    SpaceGrantResponse,
    SpaceResponse,
    SpaceUpdateRequest,
)
from deerflow.persistence.knowledge.model import KnowledgeDocumentRow, KnowledgeGrantRow, KnowledgeSpaceRow

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SPACE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

ROLE_RANK = {"viewer": 1, "editor": 2, "publisher": 3, "admin": 4}


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
            or_(KnowledgeGrantRow.expires_at.is_(None), KnowledgeGrantRow.expires_at > datetime.now(UTC)),
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
                or_(KnowledgeGrantRow.expires_at.is_(None), KnowledgeGrantRow.expires_at > datetime.now(UTC)),
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

    from deerflow.persistence.knowledge.model import KnowledgeGrantRow, KnowledgeSpaceRow

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
            updated_at=datetime.now(UTC),
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


async def resolve_bound_scenario(
    session: AsyncSession,
    scenario: str | None,
    default_scenarios: list[str] | None = None,
) -> str:

    raw = (scenario or "").strip()
    if not raw and default_scenarios:
        raw = str(default_scenarios[0] or "").strip()
    return await validate_scenario_code(session, raw)


def resolve_space_allowed_kinds(requested: list[str] | None = None) -> list[str]:
    """Space document kind whitelist; kinds are user-defined in pub_codes."""
    want = [k for k in (requested or []) if k]
    return want if want else ["general"]


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
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


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
        scenarios_list = [bound]
    else:
        scenarios_list = []
    kinds = resolve_space_allowed_kinds(allowed_kinds)

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

    created = datetime.now(UTC)
    row = KnowledgeSpaceRow(
        id=candidate,
        name=name.strip(),
        description=(description.strip() if description else None) or None,
        access=access if access in ("open", "members", "private") else "open",
        owner_user_id=user_id,
        allowed_kinds=kinds,
        default_scenarios=scenarios_list,
        created_at=created,
        updated_at=created,
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
    existing.updated_at = datetime.now(UTC)
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
    from deerflow.knowledge.app.codes import delete_scenario as delete_scenario_row
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
        from deerflow.knowledge.app.documents import delete_space

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
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
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
    ts = datetime.now(UTC)
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
            created_at=ts,
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


def ensure_kind_allowed(*, kind: str, space_allowed_kinds: list[str] | None) -> str:
    from fastapi import HTTPException

    kid = (kind or "").strip() or "general"
    allowed = [k for k in (space_allowed_kinds or []) if k]
    if allowed and kid not in allowed:
        raise HTTPException(status_code=422, detail=f"kind '{kid}' not allowed in this space")
    return kid
