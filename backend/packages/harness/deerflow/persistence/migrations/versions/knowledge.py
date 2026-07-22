"""Create knowledge_spaces / knowledge_grants / knowledge_documents.

Revision ID: knowledge
Revises:
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "knowledge"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("knowledge_spaces"):
        # Idempotent: empty-DB bootstrap runs create_all (full metadata) then
        # stamps head; legacy seeds may also pre-provision these tables.
        return

    op.create_table(
        "knowledge_spaces",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("access", sa.String(length=32), nullable=False, server_default="members"),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("allowed_kinds", sa.JSON(), nullable=False),
        sa.Column("default_scenarios", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attrs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledge_spaces_owner_user_id", "knowledge_spaces", ["owner_user_id"])

    op.create_table(
        "knowledge_grants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("resource_type", sa.String(length=16), nullable=False, server_default="space"),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("space_id", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("granted_by", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["knowledge_spaces.id"],
            name="fk_knowledge_grants_space_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            "subject_type",
            "subject_id",
            name="uq_knowledge_grant",
        ),
    )
    op.create_index("ix_knowledge_grants_space_id", "knowledge_grants", ["space_id"])
    op.create_index("ix_knowledge_grants_resource_id", "knowledge_grants", ["resource_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("space_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="zh-CN"),
        sa.Column("sensitivity", sa.String(length=32), nullable=False, server_default="internal"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="processing"),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=256), nullable=False, server_default="application/octet-stream"),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("external_id", sa.String(length=256), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("attrs", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("job_phase", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_quality", sa.String(length=32), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["knowledge_spaces.id"],
            name="fk_knowledge_documents_space_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_knowledge_documents_space_id", "knowledge_documents", ["space_id"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])


def downgrade() -> None:
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_grants")
    op.drop_table("knowledge_spaces")
