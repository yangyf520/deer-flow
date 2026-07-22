"""ORM models for knowledge P0 tables."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deerflow.persistence.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class KnowledgeSpaceRow(Base):
    __tablename__ = "knowledge_spaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    access: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    allowed_kinds: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    default_scenarios: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attrs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    grants: Mapped[list[KnowledgeGrantRow]] = relationship(
        "KnowledgeGrantRow",
        back_populates="space",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    documents: Mapped[list[KnowledgeDocumentRow]] = relationship(
        "KnowledgeDocumentRow",
        back_populates="space",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeGrantRow(Base):
    """Unified ACL grant: resource (space|document) + subject (user|dept) + role."""

    __tablename__ = "knowledge_grants"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "subject_type",
            "subject_id",
            name="uq_knowledge_grant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False, default="space")  # space | document
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Denormalized space for CASCADE + listing; equals resource_id when resource_type=space.
    space_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE", name="fk_knowledge_grants_space_id"),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user | dept
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    space: Mapped[KnowledgeSpaceRow] = relationship("KnowledgeSpaceRow", back_populates="grants")


class KnowledgeDocumentRow(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE", name="fk_knowledge_documents_space_id"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing", index=True)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(256), nullable=False, default="application/octet-stream")
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    attrs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job_phase: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    space: Mapped[KnowledgeSpaceRow] = relationship("KnowledgeSpaceRow", back_populates="documents")
