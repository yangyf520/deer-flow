"""No-op placeholder — revision kept for alembic history compatibility.

The prefix_suffix experiment was removed; display masking lives in the frontend
``maskMiddle`` helper instead. DBs already stamped at this revision must retain
the revision id so ``alembic upgrade head`` can resolve the chain.

Revision ID: 0011_user_api_keys_prefix_suffix
Revises: 0010_pub_codes
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

revision = "0011_user_api_keys_prefix_suffix"
down_revision: str | Sequence[str] | None = "0010_pub_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
