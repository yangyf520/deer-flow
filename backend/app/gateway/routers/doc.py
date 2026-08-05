"""Document Gateway routes — stateless structured parse (no DB write)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.doc_parse.contract import DocParseResponse
from deerflow.doc_parse.pipeline import DocParseError, parse_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/document", tags=["document"])


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
