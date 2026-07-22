"""Create user_api_keys table for per-user programmatic access tokens.

Revision ID: user_api_keys
Revises: 0005_run_stop_reason, agents
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "user_api_keys"
down_revision: str | Sequence[str] | None = ("0005_run_stop_reason", "agents")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("user_api_keys"):
        op.create_table(
            "user_api_keys",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.String(length=512), nullable=True),
            sa.Column("prefix", sa.String(length=16), nullable=False),
            sa.Column("key_hash", sa.String(length=128), nullable=False),
            sa.Column("agent_name", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("user_api_keys", schema=None) as batch_op:
            batch_op.create_index("ix_user_api_keys_user_id", ["user_id"], unique=False)
            batch_op.create_index("ix_user_api_keys_prefix", ["prefix"], unique=False)
        return
    columns = {column["name"] for column in inspector.get_columns("user_api_keys")}
    if "description" not in columns:
        with op.batch_alter_table("user_api_keys", schema=None) as batch_op:
            batch_op.add_column(sa.Column("description", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_user_api_keys_prefix", table_name="user_api_keys")
    op.drop_index("ix_user_api_keys_user_id", table_name="user_api_keys")
    op.drop_table("user_api_keys")
