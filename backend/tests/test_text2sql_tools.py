"""Tests for business-database tools (deerflow.community.text2sql)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


def test_db_schema_requires_config(monkeypatch):
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("DB_TYPE", raising=False)

    from deerflow.community.text2sql.tools import db_schema_tool

    with pytest.raises(RuntimeError, match="not configured"):
        db_schema_tool.invoke({})


def test_db_query_returns_json(monkeypatch):
    monkeypatch.setenv("DB_TYPE", "postgres")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USERNAME", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")

    from deerflow.community.text2sql.tools import db_query_tool

    with patch("deerflow.community.text2sql.tools.query", return_value=([{"n": 1}], False)):
        raw = db_query_tool.invoke({"sql": "SELECT 1"})
    data = json.loads(raw)
    assert data["count"] == 1


def test_business_db_configured(monkeypatch):
    from deerflow.utils.database import is_business_db_configured

    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("DB_TYPE", raising=False)
    assert is_business_db_configured() is False
    monkeypatch.setenv("DB_TYPE", "postgres")
    assert is_business_db_configured() is True
