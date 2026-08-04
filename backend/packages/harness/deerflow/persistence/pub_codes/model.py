"""Generic code table (码表) — user-managed catalog entries by domain."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PubCodeRow(Base):
    """System code table row: machine ``code`` + display ``label`` per domain/type."""

    __tablename__ = "pub_codes"
    __table_args__ = (UniqueConstraint("domain", "type_key", "parent_code", "code", name="uq_pub_codes"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    type_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # Scenario code for kinds/tags/tag_groups; empty for top-level scenarios.
    parent_code: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    attrs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
