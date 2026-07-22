"""Add description column to user_api_keys.

Revision ID: user_api_keys_description
Revises: user_api_keys
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "user_api_keys_description"
down_revision: str | Sequence[str] | None = "user_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("user_api_keys"):
        return
    columns = {column["name"] for column in inspector.get_columns("user_api_keys")}
    if "description" in columns:
        return
    with op.batch_alter_table("user_api_keys", schema=None) as batch_op:
        batch_op.add_column(sa.Column("description", sa.String(length=512), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("user_api_keys"):
        return
    columns = {column["name"] for column in inspector.get_columns("user_api_keys")}
    if "description" not in columns:
        return
    with op.batch_alter_table("user_api_keys", schema=None) as batch_op:
        batch_op.drop_column("description")
