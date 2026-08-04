"""Document Gateway routes — parse (structured JSON) and embed (knowledge ingest)."""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.gateway.authz import require_auth, require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.doc_parse.contract import DocParseResponse
from deerflow.doc_parse.pipeline import DocParseError, parse_document
from deerflow.knowledge import service as knowledge_service
from deerflow.knowledge.service import DocumentImportResponse, require_knowledge_extra
from deerflow.persistence.engine import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/doc", tags=["doc"])


def _session_factory():
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    return factory


def _user(request: Request):
    auth = getattr(request.state, "auth", None)
    if auth is None or auth.user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return auth.user


def _uid(user) -> str:
    return str(user.id)


@router.post(
    "/parse",
    response_model=DocParseResponse,
    summary="Parse Document into Structured JSON",
    description=("Upload a file with segment_prompt. Uses Docling + LlamaIndex markdown split + batched run_oneshot_llm; returns {data, meta}. No LangGraph run, no DB write."),
)
@require_permission("runs", "create")
async def parse_doc(
    request: Request,
    file: UploadFile = File(..., description="Document to parse"),
    segment_prompt: str = Form(..., description="Segmentation instructions and JSON shape"),
    output_schema: str | None = Form(None, description="Optional JSON Schema for data"),
    config: AppConfig = Depends(get_config),
) -> DocParseResponse:
    del request

    filename = file.filename or "document.bin"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    schema: dict | None = None
    if output_schema and output_schema.strip():
        try:
            parsed_schema = json.loads(output_schema)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"invalid output_schema JSON: {exc}") from exc
        if not isinstance(parsed_schema, dict):
            raise HTTPException(status_code=422, detail="output_schema must be a JSON object")
        schema = parsed_schema

    try:
        return await parse_document(
            data=data,
            filename=filename,
            segment_prompt=segment_prompt,
            output_schema=schema,
            app_config=config,
        )
    except DocParseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.exception("doc_parse failed for %s: %s", filename, exc)
        raise HTTPException(status_code=503, detail="Failed to parse document") from exc


@router.post(
    "/embed/{space_id}",
    response_model=DocumentImportResponse,
    status_code=201,
    summary="Embed document into a knowledge space",
    description=("Upload a file to parse, chunk, and vectorize into the given knowledge space. Pairs with POST /api/doc/parse for structured upload (parse → preview → embed)."),
)
@require_auth
@require_permission("knowledge", "write")
async def embed_doc(
    space_id: str,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    kind: str = Form(...),
    tags: Annotated[list[str], Form()] = [],
) -> DocumentImportResponse:
    require_knowledge_extra()
    user = _user(request)
    factory = _session_factory()
    async with factory() as session:
        await knowledge_service.get_space_or_404(
            session,
            space_id=space_id,
            user_id=_uid(user),
            system_role=user.system_role,
            min_role="editor",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    return await knowledge_service.import_document(
        factory,
        space_id=space_id,
        user_id=_uid(user),
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        title=title,
        kind=kind,
        tags=tags or None,
    )
