"""Knowledge documents: import, ingest, and CRUD."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.knowledge.adapters.storage import delete_document_vectors, delete_space_vectors, list_document_chunks, sync_document_metadata
from deerflow.knowledge.app.spaces import ensure_kind_allowed, get_space_or_404, space_knowledge_version
from deerflow.knowledge.contract import (
    DocumentChunkItem,
    DocumentChunksResponse,
    DocumentImportResponse,
    DocumentResponse,
    EmbedSegment,
)
from deerflow.knowledge.engine.evidence import merge_custom_metadata, parse_as_of
from deerflow.knowledge.engine.index import index_document
from deerflow.knowledge.engine.parse import parse_upload_bytes
from deerflow.persistence.knowledge.model import KnowledgeDocumentRow, KnowledgeSpaceRow

logger = logging.getLogger(__name__)


def _display_name_from_email(email: str | None, user_id: str) -> str:
    raw = (email or "").strip()
    if not raw:
        return user_id
    local = raw.split("@", 1)[0].strip()
    return local or raw


def doc_to_response(row: KnowledgeDocumentRow, *, created_by_name: str | None = None) -> DocumentResponse:
    return DocumentResponse(
        id=row.id,
        space_id=row.space_id,
        title=row.title,
        kind=row.kind,
        tags=[str(t) for t in (row.tags or []) if str(t).strip()],
        language=row.language,
        sensitivity=row.sensitivity,
        status=row.status,
        source_filename=row.source_filename,
        source_uri=row.source_uri,
        content_type=row.content_type,
        byte_size=row.byte_size,
        job_phase=row.job_phase,
        progress=row.progress,
        parse_quality=row.parse_quality,
        parse_error=row.parse_error,
        error_message=row.error_message,
        created_by=row.created_by,
        created_by_name=created_by_name,
        effective_from=row.effective_from.isoformat() if row.effective_from else None,
        effective_to=row.effective_to.isoformat() if row.effective_to else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        attrs=dict(row.attrs or {}) if isinstance(getattr(row, "attrs", None), dict) else {},
    )


async def resolve_user_display_names(session: AsyncSession, user_ids: Iterable[str]) -> dict[str, str]:
    """Map user_id → display name (email local-part). Missing users omitted."""
    ids = sorted({str(u).strip() for u in user_ids if u and str(u).strip()})
    if not ids:
        return {}
    from deerflow.persistence.user.model import UserRow

    rows = list((await session.execute(select(UserRow).where(UserRow.id.in_(ids)))).scalars().all())
    return {r.id: _display_name_from_email(r.email, r.id) for r in rows}


async def list_documents(
    session: AsyncSession,
    space_id: str,
    *,
    kind: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[DocumentResponse], int]:
    filters = [KnowledgeDocumentRow.space_id == space_id]
    kind_filter = (kind or "").strip()
    if kind_filter:
        filters.append(KnowledgeDocumentRow.kind == kind_filter)
    q_filter = (q or "").strip()
    if q_filter:
        pattern = f"%{q_filter}%"
        filters.append(
            or_(
                KnowledgeDocumentRow.title.ilike(pattern),
                KnowledgeDocumentRow.source_filename.ilike(pattern),
            )
        )

    total = await session.scalar(select(func.count()).select_from(KnowledgeDocumentRow).where(*filters))
    result = await session.execute(select(KnowledgeDocumentRow).where(*filters).order_by(KnowledgeDocumentRow.created_at.desc()).limit(limit).offset(offset))
    rows = list(result.scalars().all())
    names = await resolve_user_display_names(session, [r.created_by for r in rows])
    return [doc_to_response(r, created_by_name=names.get(r.created_by)) for r in rows], int(total or 0)


async def get_document_chunks(
    session: AsyncSession,
    *,
    space_id: str,
    doc_id: str,
) -> DocumentChunksResponse:
    from fastapi import HTTPException

    row = await session.get(KnowledgeDocumentRow, doc_id)
    if row is None or row.space_id != space_id:
        raise HTTPException(status_code=404, detail="Document not found")
    raw = await asyncio.to_thread(list_document_chunks, space_id=space_id, doc_id=doc_id)
    items = [DocumentChunkItem.model_validate(x) for x in raw]
    return DocumentChunksResponse(
        doc_id=row.id,
        title=row.title,
        source_filename=row.source_filename,
        parse_quality=row.parse_quality,
        parse_error=row.parse_error,
        items=items,
        total=len(items),
    )


async def delete_document(
    session: AsyncSession,
    *,
    space_id: str,
    doc_id: str,
) -> None:
    """Delete vectors (best-effort), then the document DB row."""
    from fastapi import HTTPException

    row = await session.get(KnowledgeDocumentRow, doc_id)
    if row is None or row.space_id != space_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        await asyncio.to_thread(delete_document_vectors, space_id=space_id, doc_id=doc_id)
    except Exception as exc:
        # Prefer removing the DB row over leaving an undeletable failed ingest.
        logger.exception("vector delete failed for %s (continuing with DB delete): %s", doc_id, exc)

    try:
        await session.delete(row)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("db delete failed for %s", doc_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document. {exc}",
        ) from exc


async def delete_all_documents(
    session: AsyncSession,
    *,
    space_id: str,
) -> int:
    """Delete every document in a space (vectors best-effort, then DB rows)."""
    from fastapi import HTTPException

    result = await session.execute(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.space_id == space_id))
    docs = list(result.scalars().all())
    if not docs:
        return 0

    for row in docs:
        try:
            await asyncio.to_thread(
                delete_document_vectors,
                space_id=space_id,
                doc_id=row.id,
            )
        except Exception as exc:
            logger.exception(
                "vector delete failed for %s (continuing with DB delete): %s",
                row.id,
                exc,
            )

    try:
        for row in docs:
            await session.delete(row)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("bulk document delete failed for space %s", space_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete documents. {exc}",
        ) from exc

    return len(docs)


async def delete_space(
    session: AsyncSession,
    *,
    space_id: str,
    user_id: str,
    system_role: str,
) -> None:
    """Delete a space and cascade: vectors → DB (grants+docs via FK).

    Requires space admin (or system admin per authz config).
    """
    from fastapi import HTTPException

    space, _ = await get_space_or_404(
        session,
        space_id=space_id,
        user_id=user_id,
        system_role=system_role,
        min_role="admin",
    )

    result = await session.execute(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.space_id == space_id))
    docs = list(result.scalars().all())
    doc_ids = [d.id for d in docs]

    try:
        for did in doc_ids:
            await asyncio.to_thread(delete_document_vectors, space_id=space_id, doc_id=did)
        await asyncio.to_thread(delete_space_vectors, space_id=space_id)
    except Exception as exc:
        # Prefer removing the DB row over leaving an undeletable space.
        logger.exception("space vector delete failed for %s (continuing with DB delete): %s", space_id, exc)

    try:
        await session.delete(space)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("space db delete failed for %s", space_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete space. {exc}",
        ) from exc


async def import_document(
    session_factory: async_sessionmaker,
    *,
    space_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    data: bytes,
    title: str | None = None,
    kind: str = "general",
    tags: list[str] | None = None,
    attrs: dict[str, Any] | None = None,
    segments: list[EmbedSegment] | None = None,
) -> DocumentImportResponse:
    from fastapi import HTTPException

    if not data and not segments:
        raise HTTPException(status_code=400, detail="file or segments required")

    if segments:
        payload = json.dumps([s.model_dump() for s in segments], ensure_ascii=False, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
    else:
        checksum = hashlib.sha256(data).hexdigest()

    async with session_factory() as session:
        space = await session.get(KnowledgeSpaceRow, space_id)
        if space is None:
            raise HTTPException(status_code=404, detail="Space not found")
        kind = ensure_kind_allowed(kind=kind, space_allowed_kinds=list(space.allowed_kinds or []))
        tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()]

        # Same bytes in the same space → reuse (no duplicate vectors).
        existing = (
            (
                await session.execute(
                    select(KnowledgeDocumentRow).where(
                        KnowledgeDocumentRow.space_id == space_id,
                        KnowledgeDocumentRow.checksum_sha256 == checksum,
                        KnowledgeDocumentRow.status.in_(("ready", "processing")),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            if attrs:
                merged_attrs = dict(existing.attrs or {}) if isinstance(existing.attrs, dict) else {}
                merged_attrs.update(merge_custom_metadata({}, attrs))
                existing.attrs = merged_attrs
                existing.updated_at = datetime.now(UTC)
                await session.commit()
            logger.info(
                "import deduped space=%s checksum=%s existing=%s",
                space_id,
                checksum[:12],
                existing.id,
            )
            return DocumentImportResponse(
                doc_id=existing.id,
                status=existing.status,
                job_phase=existing.job_phase,
                progress=existing.progress,
                deduped=True,
                message=None,
            )

        # Failed prior upload with same checksum → replace (delete old shards first).
        failed = (
            (
                await session.execute(
                    select(KnowledgeDocumentRow).where(
                        KnowledgeDocumentRow.space_id == space_id,
                        KnowledgeDocumentRow.checksum_sha256 == checksum,
                        KnowledgeDocumentRow.status == "failed",
                    )
                )
            )
            .scalars()
            .first()
        )
        if failed is not None:
            await delete_document(session, space_id=space_id, doc_id=failed.id)

        doc_id = str(uuid.uuid4())
        created = datetime.now(UTC)
        default_title = Path(filename).stem.strip() or filename
        doc_attrs = merge_custom_metadata({}, attrs)
        row = KnowledgeDocumentRow(
            id=doc_id,
            space_id=space_id,
            title=title or default_title,
            kind=kind or "general",
            tags=tag_list,
            attrs=doc_attrs,
            status="processing",
            source_filename=filename,
            source_uri="",
            content_type=content_type or "application/octet-stream",
            byte_size=len(data) if data else None,
            checksum_sha256=checksum,
            job_phase="queued",
            progress=0,
            created_by=user_id,
            created_at=created,
            updated_at=created,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        response = DocumentImportResponse(
            doc_id=row.id,
            status=row.status,
            job_phase=row.job_phase,
            progress=row.progress,
            deduped=False,
            message=None,
        )

    # background ingest
    segment_payload = [s.model_dump() for s in segments] if segments else None
    asyncio.create_task(
        run_ingest(
            session_factory,
            doc_id=doc_id,
            data=data,
            filename=filename,
            segments=segment_payload,
        )
    )
    return response


async def run_ingest(
    session_factory: async_sessionmaker,
    *,
    doc_id: str,
    data: bytes,
    filename: str,
    segments: list[dict[str, Any]] | None = None,
) -> None:
    async with session_factory() as session:
        row = await session.get(KnowledgeDocumentRow, doc_id)
        if row is None:
            return
        try:
            row.job_phase = "parsing"
            row.progress = 20
            row.updated_at = datetime.now(UTC)
            await session.commit()

            structured_docs = None
            parsed_text = ""
            parse_quality = "ok"
            parse_error = None
            if segments:
                from llama_index.core import Document

                structured_docs = [Document(text=str(seg.get("text") or "").strip(), metadata=dict(seg.get("metadata") or {})) for seg in segments if str(seg.get("text") or "").strip()]
                parsed_text = "\n\n".join(str(seg.get("text") or "").strip() for seg in segments)
            else:
                parsed = await parse_upload_bytes(data, filename)
                parse_quality = parsed.parse_quality
                parse_error = parsed.error
                parsed_text = parsed.text
                if parsed.parse_quality == "failed" or not parsed.text.strip():
                    row.parse_quality = parsed.parse_quality
                    row.parse_error = parsed.error
                    row.status = "failed"
                    row.job_phase = "failed"
                    row.progress = 100
                    row.error_message = parsed.error or "parse failed"
                    row.updated_at = datetime.now(UTC)
                    await session.commit()
                    return

            row.parse_quality = parse_quality
            row.parse_error = parse_error
            if not parsed_text.strip():
                row.status = "failed"
                row.job_phase = "failed"
                row.progress = 100
                row.error_message = parse_error or "empty content"
                row.updated_at = datetime.now(UTC)
                await session.commit()
                return

            row.job_phase = "embedding"
            row.progress = 60
            row.updated_at = datetime.now(UTC)
            await session.commit()

            space = await session.get(KnowledgeSpaceRow, row.space_id)
            release = space_knowledge_version(space)
            doc_attrs = dict(row.attrs or {}) if isinstance(row.attrs, dict) else {}

            await asyncio.to_thread(
                index_document,
                space_id=row.space_id,
                doc_id=row.id,
                title=row.title,
                kind=row.kind,
                sensitivity=row.sensitivity,
                text=parsed_text,
                parse_quality=parse_quality,
                documents=structured_docs,
                tags=list(row.tags or []),
                release=release,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                doc_attrs=doc_attrs,
            )

            row.status = "ready"
            row.job_phase = "ready"
            row.progress = 100
            row.updated_at = datetime.now(UTC)
            await session.commit()
        except Exception as exc:
            logger.exception("ingest failed for %s", doc_id)
            row.status = "failed"
            row.job_phase = "failed"
            row.progress = 100
            row.error_message = str(exc)
            row.updated_at = datetime.now(UTC)
            await session.commit()


async def reindex_document(
    session_factory: async_sessionmaker,
    *,
    space_id: str,
    doc_id: str,
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> DocumentResponse:
    """Re-parse + re-embed an existing document from uploaded file bytes."""
    if not data:
        raise HTTPException(status_code=422, detail="file required for reindex")

    checksum = hashlib.sha256(data).hexdigest()
    async with session_factory() as session:
        row = await session.get(KnowledgeDocumentRow, doc_id)
        if row is None or row.space_id != space_id:
            raise HTTPException(status_code=404, detail="Document not found")
        if row.status == "processing":
            raise HTTPException(status_code=409, detail="Document is already processing")
        safe_filename = (filename or row.source_filename or "file.bin").strip() or "file.bin"
        row.source_filename = safe_filename
        if content_type:
            row.content_type = content_type
        row.byte_size = len(data)
        row.checksum_sha256 = checksum
        row.source_uri = ""
        row.status = "processing"
        row.job_phase = "queued"
        row.progress = 0
        row.error_message = None
        row.parse_error = None
        row.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
        names = await resolve_user_display_names(session, [row.created_by])
        response = doc_to_response(row, created_by_name=names.get(row.created_by))

    asyncio.create_task(run_ingest(session_factory, doc_id=doc_id, data=data, filename=safe_filename))
    return response


async def update_document(
    session: AsyncSession,
    *,
    space_id: str,
    doc_id: str,
    kind: str | None = None,
    tags: list[str] | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    title: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> DocumentResponse:
    row = await session.get(KnowledgeDocumentRow, doc_id)
    if row is None or row.space_id != space_id:
        raise HTTPException(status_code=404, detail="Document not found")

    space = await session.get(KnowledgeSpaceRow, space_id)
    meta_patch: dict[str, Any] = {}

    if title is not None:
        row.title = title.strip()
        meta_patch["title"] = row.title
    if kind is not None:
        kid = ensure_kind_allowed(kind=kind, space_allowed_kinds=list(space.allowed_kinds or []) if space else [])
        row.kind = kid
        meta_patch["kind"] = kid
    if tags is not None:
        row.tags = [str(t).strip() for t in tags if str(t).strip()]
        meta_patch["tags"] = ",".join(row.tags or [])
    if effective_from is not None:
        row.effective_from = parse_as_of(str(effective_from).strip()) if str(effective_from).strip() else None
        if row.effective_from is not None:
            meta_patch["effective_from"] = row.effective_from.isoformat()
    if effective_to is not None:
        row.effective_to = parse_as_of(str(effective_to).strip()) if str(effective_to).strip() else None
        meta_patch["effective_to"] = row.effective_to.isoformat() if row.effective_to is not None else None
    if attrs is not None:
        merged_attrs = dict(row.attrs or {}) if isinstance(row.attrs, dict) else {}
        merged_attrs.update(merge_custom_metadata({}, attrs))
        row.attrs = merged_attrs
        meta_patch.update(merge_custom_metadata({}, attrs))
    row.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)

    if space is not None:
        meta_patch.setdefault("release", space_knowledge_version(space))
    if meta_patch:
        await asyncio.to_thread(
            sync_document_metadata,
            space_id=space_id,
            doc_id=doc_id,
            patch=meta_patch,
        )

    names = await resolve_user_display_names(session, [row.created_by])
    return doc_to_response(row, created_by_name=names.get(row.created_by))
