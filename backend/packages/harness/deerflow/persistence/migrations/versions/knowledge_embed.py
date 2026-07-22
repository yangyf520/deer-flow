"""Rename LlamaIndex vector table to knowledge_embed.

Revision ID: knowledge_embed
Revises: knowledge
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op

revision = "knowledge_embed"
down_revision = "knowledge"
branch_labels = None
depends_on = None

_OLD = "data_knowledge_embeddings"
_NEW = "knowledge_embed"


def upgrade() -> None:
    # Vector table is created by LlamaIndex at runtime; rename if the old name exists.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('public.{_OLD}') IS NOT NULL
               AND to_regclass('public.{_NEW}') IS NULL THEN
                ALTER TABLE {_OLD} RENAME TO {_NEW};
            END IF;
            IF to_regclass('public.{_OLD}_embedding_idx') IS NOT NULL
               AND to_regclass('public.{_NEW}_embedding_idx') IS NULL THEN
                ALTER INDEX {_OLD}_embedding_idx RENAME TO {_NEW}_embedding_idx;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('public.{_NEW}') IS NOT NULL
               AND to_regclass('public.{_OLD}') IS NULL THEN
                ALTER TABLE {_NEW} RENAME TO {_OLD};
            END IF;
            IF to_regclass('public.{_NEW}_embedding_idx') IS NOT NULL
               AND to_regclass('public.{_OLD}_embedding_idx') IS NULL THEN
                ALTER INDEX {_NEW}_embedding_idx RENAME TO {_OLD}_embedding_idx;
            END IF;
        END $$;
        """
    )
