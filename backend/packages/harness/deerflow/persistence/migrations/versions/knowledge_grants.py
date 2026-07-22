"""Rename legacy grant tables → knowledge_grants; add resource columns.

Revision ID: knowledge_grants
Revises: knowledge_embed
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "knowledge_grants"
down_revision = "knowledge_embed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "knowledge_space_members" in tables and "knowledge_grants" not in tables:
        if "knowledge_space_grants" in tables:
            pass  # prefer renaming space_grants below
        else:
            op.rename_table("knowledge_space_members", "knowledge_grants")
            tables.discard("knowledge_space_members")
            tables.add("knowledge_grants")

    if "knowledge_space_grants" in tables and "knowledge_grants" not in tables:
        op.rename_table("knowledge_space_grants", "knowledge_grants")
        tables.discard("knowledge_space_grants")
        tables.add("knowledge_grants")

    if "knowledge_grants" not in tables:
        return

    cols = {c["name"] for c in inspector.get_columns("knowledge_grants")}
    if "resource_type" not in cols:
        op.add_column(
            "knowledge_grants",
            sa.Column("resource_type", sa.String(length=16), nullable=False, server_default="space"),
        )
    if "resource_id" not in cols:
        op.add_column("knowledge_grants", sa.Column("resource_id", sa.String(length=64), nullable=True))
        op.execute("UPDATE knowledge_grants SET resource_id = space_id WHERE resource_id IS NULL")
        op.alter_column("knowledge_grants", "resource_id", nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "knowledge_grants" in tables and "knowledge_space_grants" not in tables:
        op.rename_table("knowledge_grants", "knowledge_space_grants")
