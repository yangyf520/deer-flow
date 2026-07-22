"""User API key repository, token helpers, and CRUD routes."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.auth.password import hash_password, verify_password
from deerflow.persistence.user.api_key_model import UserApiKeyRow

API_KEY_PREFIX = "dfk_"
_PREFIX_DISPLAY_LEN = 8
_UNSET = object()

router = APIRouter(prefix="/api/v1/auth/api-keys", tags=["auth"])


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    id: str
    user_id: str
    name: str
    description: str | None
    prefix: str
    key_hash: str
    agent_name: str | None
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class CreatedApiKey:
    id: str
    name: str
    description: str | None
    prefix: str
    key: str
    agent_name: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedApiKey:
    id: str
    user_id: str
    agent_name: str | None


class ApiKeyRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_record(row: UserApiKeyRow) -> ApiKeyRecord:
        created_at = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
        revoked_at = row.revoked_at
        if revoked_at is not None and revoked_at.tzinfo is None:
            revoked_at = revoked_at.replace(tzinfo=UTC)
        return ApiKeyRecord(
            id=row.id,
            user_id=row.user_id,
            name=row.name,
            description=row.description,
            prefix=row.prefix,
            key_hash=row.key_hash,
            agent_name=row.agent_name,
            created_at=created_at,
            revoked_at=revoked_at,
        )

    async def create(
        self,
        *,
        key_id: str,
        user_id: str,
        name: str,
        prefix: str,
        key_hash: str,
        agent_name: str | None,
        created_at: datetime,
        description: str | None = None,
    ) -> ApiKeyRecord:
        row = UserApiKeyRow(
            id=key_id,
            user_id=user_id,
            name=name,
            description=description,
            prefix=prefix,
            key_hash=key_hash,
            agent_name=agent_name,
            created_at=created_at,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._row_to_record(row)

    async def list_for_user(self, user_id: str) -> list[ApiKeyRecord]:
        stmt = select(UserApiKeyRow).where(UserApiKeyRow.user_id == user_id, UserApiKeyRow.revoked_at.is_(None)).order_by(UserApiKeyRow.created_at.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_record(row) for row in result.scalars()]

    async def list_active_by_prefix(self, prefix: str) -> list[ApiKeyRecord]:
        stmt = select(UserApiKeyRow).where(
            UserApiKeyRow.prefix == prefix,
            UserApiKeyRow.revoked_at.is_(None),
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_record(row) for row in result.scalars()]

    async def update(
        self,
        *,
        user_id: str,
        key_id: str,
        name: str | None = None,
        description: str | None | object = _UNSET,
        agent_name: str | None | object = _UNSET,
    ) -> ApiKeyRecord | None:
        async with self._sf() as session:
            row = await session.get(UserApiKeyRow, key_id)
            if row is None or row.user_id != user_id or row.revoked_at is not None:
                return None
            if name is not None:
                row.name = name
            if description is not _UNSET:
                row.description = description  # type: ignore[assignment]
            if agent_name is not _UNSET:
                row.agent_name = agent_name  # type: ignore[assignment]
            await session.commit()
            await session.refresh(row)
            return self._row_to_record(row)

    async def revoke(self, *, user_id: str, key_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(UserApiKeyRow, key_id)
            if row is None or row.user_id != user_id or row.revoked_at is not None:
                return False
            row.revoked_at = datetime.now(UTC)
            await session.commit()
            return True


def _normalize_agent_name(agent_name: str | None) -> str | None:
    if agent_name is None:
        return None
    normalized = agent_name.strip().lower().replace("_", "-")
    return normalized or None


def _normalize_description(description: str | None) -> str | None:
    if description is None:
        return None
    normalized = description.strip()
    return normalized or None


def generate_api_key_token() -> tuple[str, str]:
    """Return (full_token, lookup_prefix)."""
    secret = secrets.token_urlsafe(32)
    token = f"{API_KEY_PREFIX}{secret}"
    lookup_prefix = secret[:_PREFIX_DISPLAY_LEN]
    return token, lookup_prefix


async def create_api_key(
    repo: ApiKeyRepository,
    *,
    user_id: str,
    name: str,
    agent_name: str | None = None,
    description: str | None = None,
) -> CreatedApiKey:
    token, lookup_prefix = generate_api_key_token()
    now = datetime.now(UTC)
    key_id = str(uuid4())
    normalized_agent = _normalize_agent_name(agent_name)
    normalized_description = _normalize_description(description)
    await repo.create(
        key_id=key_id,
        user_id=user_id,
        name=name.strip(),
        prefix=lookup_prefix,
        key_hash=hash_password(token),
        agent_name=normalized_agent,
        created_at=now,
        description=normalized_description,
    )
    return CreatedApiKey(
        id=key_id,
        name=name.strip(),
        description=normalized_description,
        prefix=f"{API_KEY_PREFIX}{lookup_prefix}",
        key=token,
        agent_name=normalized_agent,
        created_at=now,
    )


async def authenticate_api_key(repo: ApiKeyRepository, token: str) -> AuthenticatedApiKey | None:
    if not token.startswith(API_KEY_PREFIX):
        return None
    secret = token[len(API_KEY_PREFIX) :]
    if len(secret) < _PREFIX_DISPLAY_LEN:
        return None
    lookup_prefix = secret[:_PREFIX_DISPLAY_LEN]
    candidates = await repo.list_active_by_prefix(lookup_prefix)
    for row in candidates:
        if verify_password(token, row.key_hash):
            return AuthenticatedApiKey(id=row.id, user_id=row.user_id, agent_name=row.agent_name)
    return None


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    agent_name: str | None = Field(default=None, max_length=128, description="Optional bound custom agent name")


class ApiKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    agent_name: str | None = Field(default=None, max_length=128, description="Optional bound custom agent name; omit to leave unchanged")


class ApiKeySummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    prefix: str
    agent_name: str | None = None
    created_by_name: str | None = None
    created_at: datetime


class ApiKeyCreateResponse(ApiKeySummary):
    key: str = Field(..., description="Full API key — shown only once at creation")


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeySummary]


async def _agent_exists_for_user(user_id: str, agent_name: str) -> bool:
    from deerflow.persistence import agents as agent_store

    normalized = agent_name.strip().lower().replace("_", "-")
    db_result = await agent_store.name_exists_in_db_async(normalized, user_id=user_id)
    if db_result is True:
        return True
    if db_result is False:
        return agent_store.name_exists_in_files(normalized, user_id=user_id)
    return agent_store.name_exists_in_files(normalized, user_id=user_id)


async def _normalize_agent_name_for_user(user_id: str, agent_name: str | None) -> str | None:
    if agent_name is None:
        return None
    normalized = agent_name.strip().lower().replace("_", "-")
    if normalized in {"lead-agent", "lead_agent"}:
        return "lead_agent"
    if not await _agent_exists_for_user(user_id, normalized):
        raise HTTPException(status_code=400, detail=f"Agent '{agent_name}' not found")
    return normalized


def _creator_display_name(email: str) -> str:
    local = email.split("@", 1)[0].strip()
    return local or email


async def _creator_name_for_user(user_id: str) -> str | None:
    from app.gateway.deps import get_local_provider

    user = await get_local_provider().get_user(user_id)
    if user is None or not user.email:
        return None
    return _creator_display_name(user.email)


async def _summary(record: ApiKeyRecord, *, display_prefix: str) -> ApiKeySummary:
    return ApiKeySummary(
        id=record.id,
        name=record.name,
        description=record.description,
        prefix=display_prefix,
        agent_name=record.agent_name,
        created_by_name=await _creator_name_for_user(record.user_id),
        created_at=record.created_at,
    )


_routes_registered = False


def register_api_key_routes() -> APIRouter:
    """Attach CRUD routes to ``router``. Deferred to avoid import cycles with deps."""
    global _routes_registered
    if _routes_registered:
        return router

    from app.gateway.deps import get_api_key_repository, get_current_user_from_request

    @router.get("", response_model=ApiKeyListResponse)
    async def list_api_keys(
        user=Depends(get_current_user_from_request),
        repo: ApiKeyRepository = Depends(get_api_key_repository),
    ) -> ApiKeyListResponse:
        records = await repo.list_for_user(str(user.id))
        keys = [await _summary(record, display_prefix=f"dfk_{record.prefix}…") for record in records]
        return ApiKeyListResponse(keys=keys)

    @router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
    async def create_user_api_key(
        body: ApiKeyCreateRequest,
        user=Depends(get_current_user_from_request),
        repo: ApiKeyRepository = Depends(get_api_key_repository),
    ) -> ApiKeyCreateResponse:
        agent_name = await _normalize_agent_name_for_user(str(user.id), body.agent_name)

        created = await create_api_key(
            repo,
            user_id=str(user.id),
            name=body.name,
            agent_name=agent_name,
            description=body.description,
        )
        return ApiKeyCreateResponse(
            id=created.id,
            name=created.name,
            description=created.description,
            prefix=created.prefix,
            key=created.key,
            agent_name=created.agent_name,
            created_by_name=await _creator_name_for_user(str(user.id)),
            created_at=created.created_at,
        )

    @router.patch("/{key_id}", response_model=ApiKeySummary)
    async def update_api_key(
        key_id: str,
        body: ApiKeyUpdateRequest,
        user=Depends(get_current_user_from_request),
        repo: ApiKeyRepository = Depends(get_api_key_repository),
    ) -> ApiKeySummary:
        if not body.model_fields_set:
            raise HTTPException(status_code=400, detail="No fields to update")

        agent_name: str | None | object = _UNSET
        if "agent_name" in body.model_fields_set:
            agent_name = await _normalize_agent_name_for_user(str(user.id), body.agent_name)

        description: str | None | object = _UNSET
        if "description" in body.model_fields_set:
            description = _normalize_description(body.description)

        updated = await repo.update(
            user_id=str(user.id),
            key_id=key_id,
            name=body.name,
            description=description,
            agent_name=agent_name,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="API key not found")
        return await _summary(updated, display_prefix=f"dfk_{updated.prefix}…")

    @router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_api_key(
        key_id: str,
        user=Depends(get_current_user_from_request),
        repo: ApiKeyRepository = Depends(get_api_key_repository),
    ) -> None:
        revoked = await repo.revoke(user_id=str(user.id), key_id=key_id)
        if not revoked:
            raise HTTPException(status_code=404, detail="API key not found")

    _routes_registered = True
    return router
