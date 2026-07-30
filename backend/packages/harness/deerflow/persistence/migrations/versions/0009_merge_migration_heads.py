"""Merge parallel alembic branches (mainline and knowledge/api-keys).

Revision ID: 0009_merge_migration_heads
Revises: 0008_thread_operation_kind, user_api_keys_description
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0009_merge_migration_heads"
down_revision: str | Sequence[str] | None = (
    "0008_thread_operation_kind",
    "user_api_keys_description",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
