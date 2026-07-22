"""Tests for user API keys."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.gateway.auth.api_keys import ApiKeyRepository, authenticate_api_key, create_api_key, register_api_key_routes
from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRFMiddleware
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine


async def _setup_db(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'api_keys.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    assert sf is not None
    user = User(email=f"api-key-{uuid4()}@example.com", password_hash="x", system_role="user")
    created_user = await SQLiteUserRepository(sf).create_user(user)
    return sf, created_user


def _make_api_key_app(monkeypatch, session_factory):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    import app.gateway.deps as deps

    deps._cached_repo = None
    deps._cached_local_provider = None
    deps._cached_api_key_repo = ApiKeyRepository(session_factory)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.include_router(register_api_key_routes())

    @app.get("/api/protected")
    async def protected():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_create_and_authenticate_api_key(tmp_path):
    sf, user = await _setup_db(tmp_path)
    try:
        repo = ApiKeyRepository(sf)
        created = await create_api_key(
            repo,
            user_id=str(user.id),
            name="CI bot",
            agent_name="my-agent",
        )
        assert created.key.startswith("dfk_")
        assert created.agent_name == "my-agent"

        auth = await authenticate_api_key(repo, created.key)
        assert auth is not None
        assert auth.user_id == str(user.id)
        assert auth.agent_name == "my-agent"
        assert await authenticate_api_key(repo, "dfk_invalid") is None
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_revoke_api_key(tmp_path):
    sf, user = await _setup_db(tmp_path)
    try:
        repo = ApiKeyRepository(sf)
        created = await create_api_key(repo, user_id=str(user.id), name="temp")
        assert await authenticate_api_key(repo, created.key) is not None
        revoked = await repo.revoke(user_id=str(user.id), key_id=created.id)
        assert revoked is True
        assert await authenticate_api_key(repo, created.key) is None
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_update_api_key_name_agent_and_description(tmp_path):
    sf, user = await _setup_db(tmp_path)
    try:
        repo = ApiKeyRepository(sf)
        created = await create_api_key(
            repo,
            user_id=str(user.id),
            name="bot",
            agent_name=None,
            description="CI integration",
        )
        updated = await repo.update(
            user_id=str(user.id),
            key_id=created.id,
            name="CI bot",
            agent_name="lead_agent",
            description="Updated notes",
        )
        assert updated is not None
        assert updated.name == "CI bot"
        assert updated.agent_name == "lead_agent"
        assert updated.description == "Updated notes"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_update_api_key_name_and_agent(tmp_path):
    sf, user = await _setup_db(tmp_path)
    try:
        repo = ApiKeyRepository(sf)
        created = await create_api_key(repo, user_id=str(user.id), name="bot", agent_name=None)
        updated = await repo.update(
            user_id=str(user.id),
            key_id=created.id,
            name="CI bot",
            agent_name="lead_agent",
        )
        assert updated is not None
        assert updated.name == "CI bot"
        assert updated.agent_name == "lead_agent"
    finally:
        await close_engine()


def test_bearer_api_key_authenticates(monkeypatch, tmp_path):
    sf, user = asyncio.run(_setup_db(tmp_path))
    try:
        repo = ApiKeyRepository(sf)
        created = asyncio.run(
            create_api_key(repo, user_id=str(user.id), name="script"),
        )
        app = _make_api_key_app(monkeypatch, sf)
        client = TestClient(app)

        res = client.get("/api/protected", headers={"Authorization": f"Bearer {created.key}"})
        assert res.status_code == 200
        assert res.json() == {"ok": True}
    finally:
        asyncio.run(close_engine())


def test_api_key_list_via_session_cookie(monkeypatch, tmp_path):
    from app.gateway.auth import create_access_token
    from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME

    sf, user = asyncio.run(_setup_db(tmp_path))
    try:
        app = _make_api_key_app(monkeypatch, sf)
        client = TestClient(app)
        token = create_access_token(str(user.id))
        cookies = {ACCESS_TOKEN_COOKIE_NAME: token}

        list_res = client.get("/api/v1/auth/api-keys", cookies=cookies)
        assert list_res.status_code == 200
        assert list_res.json()["keys"] == []
    finally:
        asyncio.run(close_engine())
