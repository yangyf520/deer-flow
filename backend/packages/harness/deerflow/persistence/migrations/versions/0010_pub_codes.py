"""pub_codes — generic code table for user-managed catalogs.

Revision ID: 0010_pub_codes
Revises: 0009_merge_migration_heads
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_pub_codes"
down_revision: str | Sequence[str] | None = "0009_merge_migration_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("pub_codes"):
        return
    op.create_table(
        "pub_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("type_key", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("parent_code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("attrs", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain", "type_key", "parent_code", "code", name="uq_pub_codes"),
    )
    op.create_index("ix_pub_codes_domain", "pub_codes", ["domain"])
    op.create_index("ix_pub_codes_type_key", "pub_codes", ["type_key"])
    op.create_index("ix_pub_codes_parent_code", "pub_codes", ["parent_code"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("pub_codes"):
        return
    op.drop_index("ix_pub_codes_parent_code", table_name="pub_codes")
    op.drop_index("ix_pub_codes_type_key", table_name="pub_codes")
    op.drop_index("ix_pub_codes_domain", table_name="pub_codes")
    op.drop_table("pub_codes")
