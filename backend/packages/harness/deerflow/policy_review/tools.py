"""Policy review Agent tools: prepare → retrieve → finalize."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.json import parse_json_markdown
from langgraph.graph import END
from langgraph.types import Command
from pydantic import ValidationError

from deerflow.policy_review.contract import LEGAL_REVIEW_V1, DraftIn, machine_failed_result
from deerflow.policy_review.pipeline import (
    assemble_draft,
    finalize_review,
    prepare_sections,
    rebuild_retrieve_result,
    retrieve_for_sections,
)
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

MAX_FINALIZE_ATTEMPTS = 2


def sections_have_body(sections: list[Any] | None) -> bool:
    """True when at least one section carries non-empty review body text."""
    if not isinstance(sections, list):
        return False
    return any(isinstance(section, dict) and str(section.get("body") or "").strip() for section in sections)


def parse_json_arg(raw: str, *, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON for {label}: {exc}") from exc


def decode_json(raw: str) -> Any:
    return json.JSONDecoder().raw_decode(raw)[0]


def parse_json_object(raw: Any, *, label: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a JSON object or object string")
    if not raw.strip():
        raise ValueError(f"{label} is empty")
    try:
        value = parse_json_markdown(raw, parser=decode_json)
    except (json.JSONDecodeError, TypeError) as exc:
        start = raw.find("{")
        if start < 0:
            raise ValueError(f"invalid JSON for {label}: {exc}") from exc
        try:
            value = decode_json(raw[start:])
        except (json.JSONDecodeError, TypeError) as exc2:
            raise ValueError(f"invalid JSON for {label}: {exc2}") from exc2
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def parse_draft_in(raw: Any) -> DraftIn:
    """Validate tool input with contract schema (aliases coerced in FindingIn)."""
    if isinstance(raw, DraftIn):
        return raw
    if isinstance(raw, str):
        raw = parse_json_object(raw, label="draft")
    if not isinstance(raw, dict):
        raise ValueError("draft must be an object")
    # Providers often wrap as {"draft": "<json string|object>"}.
    if "draft" in raw and not raw.get("dimensions") and not raw.get("findings"):
        inner = raw.get("draft")
        if isinstance(inner, str):
            raw = parse_json_object(inner, label="draft")
        elif isinstance(inner, dict):
            raw = inner
        else:
            raise ValueError("draft wrapper must contain a JSON object or string")
        if not isinstance(raw, dict):
            raise ValueError("draft must be a JSON object")
    return DraftIn.model_validate(raw)


def failure_result(error: str, *, packs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return machine_failed_result(
        detail=error,
        packs=packs,
        next_actions=["Fix draft and rerun policy_finalize"],
    )


def finalize_attempt(runtime: Runtime) -> int:
    prior = 0
    state = getattr(runtime, "state", None) or {}
    messages = state.get("messages") if isinstance(state, dict) else None
    if isinstance(messages, list):
        for msg in messages:
            if getattr(msg, "name", None) == "policy_finalize":
                prior += 1
    return prior + 1


def load_retrieve_session(runtime: Runtime) -> dict[str, Any] | None:
    """Latest prepare/retrieve artifact that carries evidence session state."""
    state = runtime.state or {}
    messages = state.get("messages") if isinstance(state, dict) else None
    return next(
        (
            msg.artifact
            for msg in reversed(messages or [])
            if isinstance(msg, ToolMessage) and msg.name in ("policy_prepare", "policy_retrieve") and isinstance(msg.artifact, dict) and (isinstance(msg.artifact.get("scaffold"), dict) or isinstance(msg.artifact.get("packs"), list))
        ),
        None,
    )


def retry_to_model(
    *,
    tool_call_id: str,
    attempt: int,
    errors: list[str],
    warnings: list[str] | None = None,
    allowed_refs: list[str] | None = None,
    quote_pool: list[dict[str, Any]] | None = None,
    evidence_digest: list[dict[str, Any]] | None = None,
    max_attempts: int = MAX_FINALIZE_ATTEMPTS,
) -> Command:
    """Lean retry: errors + allowed_refs (+ quote_pool / evidence_digest when needed)."""
    refs = [str(x) for x in (allowed_refs or []) if str(x).strip()]
    envelope: dict[str, Any] = {
        "ok": False,
        "retry": True,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "validation": {
            "status": "fail",
            "errors": list(errors),
            "warnings": list(warnings or []),
        },
        "allowed_refs": refs,
        "fix_instructions": (
            "Fix validation.errors and call policy_finalize again. "
            "Pass draft as a JSON STRING: "
            '{"summary":"...","findings":[{"risk":"high|medium|low","text":"...","quote":"...","citation_ids":["id"],"section":"...","suggestion":"..."}]} '
            "quotes must be copied from quote_pool; citation_ids from evidence_digest. "
            "Do NOT write Markdown to the user."
        ),
    }
    if quote_pool:
        envelope["quote_pool"] = quote_pool
    if evidence_digest:
        envelope["evidence_digest"] = evidence_digest
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=json.dumps(envelope, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                    name="policy_finalize",
                )
            ]
        }
    )


def deliver_result(
    *,
    runtime: Runtime | None = None,
    tool_call_id: str,
    result: dict[str, Any],
    ok: bool,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> Command:
    """Deliver Markdown report + JSON artifact via messages only."""
    from deerflow.policy_review.render import REPORT_TITLE, humanize_error, render_report

    _ = runtime
    payload = dict(result)
    if isinstance(payload.get("summary"), str) and re.search(
        r"Field required|policy_finalize|JSON|schema|\$\.",
        payload["summary"],
        re.I,
    ):
        payload["summary"] = "本轮机器审查已完成校验处理；具体结论见下文风险详情。" if ok else "本轮机器审查未形成可交付结论，请根据校验说明处理后重试。"
    payload["report"] = render_report(payload)
    report = str(payload.get("report") or "").strip() or f"# {REPORT_TITLE}\n\n（报告生成失败）\n"
    status_line = "审查结果已生成：请查看上方 Markdown 报告；结构化 JSON 见本工具输出。" if ok else "审查未通过机器校验：请查看上方报告中的说明后重新提交。"
    if errors and not ok:
        human: list[str] = []
        seen: set[str] = set()
        for err in errors:
            label = humanize_error(str(err))
            if label and label not in seen:
                seen.add(label)
                human.append(label)
        if human:
            status_line = status_line + "\n" + "\n".join(f"- {item}" for item in human[:5])
    artifact = dict(payload)
    artifact.setdefault("schema_hint", LEGAL_REVIEW_V1)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=status_line,
                    tool_call_id=tool_call_id,
                    name="policy_finalize",
                    artifact=artifact,
                ),
                AIMessage(
                    content=report.strip() or f"# {REPORT_TITLE}\n\n（报告生成失败）\n",
                    id=f"structured-deliver:legal-review:{tool_call_id}",
                ),
            ]
        },
        goto=END,
    )


def finalize_gate(
    *,
    runtime: Runtime,
    tool_call_id: str,
    result: dict[str, Any],
    ok: bool,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    allowed_refs: list[str] | None = None,
    quote_pool: list[dict[str, Any]] | None = None,
    evidence_digest: list[dict[str, Any]] | None = None,
    max_attempts: int = MAX_FINALIZE_ATTEMPTS,
) -> Command:
    if ok:
        return deliver_result(
            runtime=runtime,
            tool_call_id=tool_call_id,
            result=result,
            ok=True,
            errors=errors,
            warnings=warnings,
        )
    attempt = finalize_attempt(runtime)
    if attempt < max_attempts:
        refs = allowed_refs
        if refs is None and isinstance(result, dict):
            audit = result.get("audit")
            if isinstance(audit, dict) and isinstance(audit.get("allowed_refs"), list):
                refs = [str(x) for x in audit["allowed_refs"] if str(x).strip()]
        pool = quote_pool
        digest = evidence_digest
        session = load_retrieve_session(runtime)
        if any("quote" in str(e).lower() for e in (errors or [])):
            if pool is None and isinstance(session, dict) and isinstance(session.get("quote_pool"), list):
                pool = session["quote_pool"]
        if digest is None and isinstance(session, dict):
            cached = rebuild_retrieve_result(session)
            digest = cached.get("evidence_digest") if isinstance(cached.get("evidence_digest"), list) else None
        return retry_to_model(
            tool_call_id=tool_call_id,
            attempt=attempt,
            errors=list(errors or []),
            warnings=warnings,
            allowed_refs=refs,
            quote_pool=pool,
            evidence_digest=digest,
            max_attempts=max_attempts,
        )
    return deliver_result(
        runtime=runtime,
        tool_call_id=tool_call_id,
        result=result,
        ok=False,
        errors=errors,
        warnings=warnings,
    )


def resolve_review_doc(runtime: Runtime, doc_path: str | None = None) -> Path:
    from deerflow.config.paths import VIRTUAL_PATH_PREFIX
    from deerflow.sandbox.tools import (
        get_thread_data,
        resolve_and_validate_user_data_path,
        validate_local_tool_path,
    )

    raw = (doc_path or "").strip()
    if not raw:
        raw = default_upload_path(runtime)
        if not raw:
            raise ValueError("no upload found; pass doc_path or upload a document in this turn")

    if not raw.startswith(("/", "\\")) and "://" not in raw:
        raw = f"{VIRTUAL_PATH_PREFIX}/uploads/{Path(raw).name}"

    thread_data = get_thread_data(runtime)
    if thread_data is None:
        raise ValueError("thread data missing; cannot resolve review document path")
    validate_local_tool_path(raw, thread_data, read_only=True)
    resolved = Path(resolve_and_validate_user_data_path(raw, thread_data))
    if not resolved.is_file():
        raise ValueError(f"document not found: {doc_path or raw}")
    return resolved


def default_upload_path(runtime: Runtime) -> str | None:
    from deerflow.config.paths import VIRTUAL_PATH_PREFIX

    state = runtime.state or {}
    uploaded = state.get("uploaded_files") or []
    if isinstance(uploaded, list):
        for entry in reversed(uploaded):
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if isinstance(path, str) and path.strip():
                return path.strip()
            filename = entry.get("filename")
            if isinstance(filename, str) and filename.strip():
                return f"{VIRTUAL_PATH_PREFIX}/uploads/{Path(filename).name}"

    thread_data = state.get("thread_data") if isinstance(state.get("thread_data"), dict) else None
    uploads_path = (thread_data or {}).get("uploads_path")
    if not uploads_path:
        return None
    uploads_dir = Path(uploads_path)
    if not uploads_dir.is_dir():
        return None
    files = [p for p in uploads_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return f"{VIRTUAL_PATH_PREFIX}/uploads/{newest.name}"


def retrieve_model_view(result: dict[str, Any]) -> dict[str, Any]:
    """Model-facing retrieve payload — full packs stay in ToolMessage.artifact only."""
    view = {
        key: result[key]
        for key in (
            "allowed_ids",
            "retrieval_empty",
            "section_results",
            "quote_pool",
            "draft_scaffold",
            "scenario",
            "evidence_digest",
            "cached",
        )
        if key in result
    }
    if "evidence_digest" not in view and isinstance(result.get("packs"), list):
        from deerflow.policy_review.pipeline import build_evidence_digest

        section_results = result.get("section_results")
        if isinstance(section_results, list):
            view["evidence_digest"] = build_evidence_digest(section_results, result["packs"])
    return view


def sections_key(sections: list[Any]) -> tuple[str, ...]:
    keys: list[str] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or section.get("section_id") or index).strip()
        keys.append(sid)
    return tuple(keys)


@tool("policy_prepare", parse_docstring=True)
async def prepare_tool(
    runtime: Runtime,
    tool_call_id: Annotated[str, InjectedToolCallId],
    doc_path: str | None = None,
    title: str | None = None,
    top_k: int | None = None,
) -> str | Command:
    """Parse uploaded docx/pdf/md via Docling and batch-retrieve evidence.

    Call this for policy / legal pre-review of an upload (parse + evidence
    retrieve). Prefer this over a plain ``read_file`` for review workflows;
    do not ask the user to convert formats.

    Prefer omitting ``doc_path`` when the user just uploaded a file — the tool
    reads the upload from agent state. After parse, the server runs section
    retrieval and stores Evidence Packs in the tool artifact for
    ``policy_finalize`` (do not re-send packs).

    Args:
        doc_path: Optional upload filename or virtual path under ``/mnt/user-data``.
            When omitted, uses this turn's uploaded file (or the newest thread upload).
        title: Optional document title override.
        top_k: Optional maximum evidence items per section.
    """
    try:
        path = resolve_review_doc(runtime, doc_path)
        prepared = prepare_sections(path, title=title)
        sections = prepared.get("sections") if isinstance(prepared, dict) else None
        if not isinstance(sections, list) or not sections:
            return json.dumps(
                {"error": "prepare produced no sections", "path": str(path)},
                ensure_ascii=False,
            )

        result, session = await retrieve_async(
            runtime,
            json.dumps({"sections": sections}, ensure_ascii=False),
            spaces=None,
            top_k=top_k,
        )
        if session is None:
            # Knowledge/auth/db unavailable — still return prepare so the model
            # can surface the error instead of silently failing the turn.
            payload = dict(prepared)
            payload["retrieve_error"] = result
            return json.dumps(payload, ensure_ascii=False)

        view = retrieve_model_view(result)
        view["prepare"] = {
            "path": str(path),
            "title": prepared.get("title") if isinstance(prepared, dict) else None,
            "section_count": len(sections),
        }
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=json.dumps(view, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name="policy_prepare",
                        artifact=session,
                    )
                ],
            }
        )
    except Exception as exc:
        logger.exception("prepare failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def retrieve_async(
    runtime: Runtime,
    sections_json: str,
    spaces: list[str] | None,
    top_k: int | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from deerflow.config.knowledge_config import get_knowledge_config
    from deerflow.knowledge.service import knowledge_extra_available
    from deerflow.persistence.engine import get_session_factory
    from deerflow.runtime.user_context import get_current_user, resolve_runtime_user_id

    if not get_knowledge_config().enabled:
        return {"error": "knowledge disabled"}, None
    if not knowledge_extra_available():
        return {"error": "knowledge extra not installed", "hint": "uv sync --extra knowledge"}, None
    user = get_current_user()
    if user is None:
        return {"error": "not authenticated"}, None
    factory = get_session_factory()
    if factory is None:
        return {"error": "database not configured"}, None

    sections = parse_json_arg(sections_json, label="sections_json")
    if isinstance(sections, dict):
        if isinstance(sections.get("sections"), list):
            sections = sections["sections"]
        elif isinstance(sections.get("section_results"), list):
            # Model sometimes re-feeds prepare/retrieve view; reuse queries there.
            sections = sections["section_results"]
    if not isinstance(sections, list):
        return {"error": "sections_json must be a JSON array of sections"}, None
    if not sections:
        return {"error": "sections_json is empty — pass prepare sections (title+body)"}, None

    # After policy_prepare, the model may re-call retrieve with section_results
    # (query only, no body). Keep prior prepare sections so quote_pool / finalize
    # still have source text.
    prior = load_retrieve_session(runtime)
    prior_sections = prior.get("sections") if isinstance(prior, dict) else None
    if sections_have_body(prior_sections) and not sections_have_body(sections):
        sections = [s for s in prior_sections if isinstance(s, dict)]

    normalized = [section for section in sections if isinstance(section, dict)]
    if isinstance(prior, dict) and isinstance(prior.get("packs"), list):
        cached_sections = [section for section in (prior.get("sections") or []) if isinstance(section, dict)]
        if cached_sections and sections_key(cached_sections) == sections_key(normalized):
            cached = rebuild_retrieve_result(prior)
            return cached, prior

    system_role = getattr(user, "system_role", None) or "user"
    result = await retrieve_for_sections(
        session_factory=factory,
        user_id=resolve_runtime_user_id(runtime),
        system_role=system_role,
        sections=sections,
        spaces=spaces,
        top_k=top_k,
    )
    session = {
        "sections": [section for section in sections if isinstance(section, dict)],
        "packs": result.get("packs") if isinstance(result.get("packs"), list) else [],
        "retrieval_empty": bool(result.get("retrieval_empty")),
        "allowed_ids": result.get("allowed_ids") if isinstance(result.get("allowed_ids"), list) else [],
        "scaffold": result.get("draft_scaffold") if isinstance(result.get("draft_scaffold"), dict) else None,
        "quote_pool": result.get("quote_pool") if isinstance(result.get("quote_pool"), list) else [],
        "spaces_queried": result.get("spaces_queried") if isinstance(result.get("spaces_queried"), list) else [],
        "evidence_digest": result.get("evidence_digest") if isinstance(result.get("evidence_digest"), list) else [],
    }
    return result, session


@tool("policy_retrieve", parse_docstring=True)
async def retrieve_tool(
    runtime: Runtime,
    sections_json: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    top_k: int | None = None,
) -> str | Command:
    """Batch-retrieve evidence for all prepared review sections.

    Pass the complete JSON returned by ``policy_prepare`` or its sections array.
    Response includes ``quote_pool`` and ``draft_scaffold``; full Evidence Packs
    stay in the tool artifact for ``policy_finalize`` (do not re-send packs).

    Args:
        sections_json: Prepared sections as a JSON object or array.
        top_k: Optional maximum evidence items per section.
    """
    try:
        result, session = await retrieve_async(runtime, sections_json, spaces=None, top_k=top_k)
        if session is None:
            return json.dumps(result, ensure_ascii=False)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=json.dumps(retrieve_model_view(result), ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name="policy_retrieve",
                        artifact=session,
                    )
                ],
            }
        )
    except Exception as exc:
        logger.exception("retrieve failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@tool("policy_finalize", parse_docstring=True)
def finalize_tool(
    runtime: Runtime,
    draft: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Validate, ground, enrich, and render a legal-review.v1 result.

    Pass ``draft`` as a **JSON string** (not a nested object) to avoid provider
    tool-argument failures::

        {"summary":"...","findings":[{"risk":"high","text":"...","quote":"...","citation_ids":["id"],"section":"...","suggestion":"..."}]}

    Server merges onto draft_scaffold from prepare/retrieve. Medium/high findings
    need citation_ids from evidence_digest. Do not resend packs.

    Args:
        draft: JSON string with summary and findings (flat list preferred).
    """
    return run_finalize(runtime=runtime, draft=draft, tool_call_id=tool_call_id)


def run_finalize(
    *,
    runtime: Runtime,
    draft: Any,
    tool_call_id: str,
    allow_retry: bool = True,
) -> Command:
    """Shared finalize path for the tool and dangling-call salvage."""
    session = load_retrieve_session(runtime)
    if not isinstance(session, dict):
        err = "policy_prepare (or policy_retrieve) must complete before policy_finalize"
        result = failure_result(err)
        return deliver_result(runtime=runtime, tool_call_id=tool_call_id, result=result, ok=False, errors=[err])

    allowed_refs = [str(x) for x in (session.get("allowed_ids") or []) if str(x).strip()]
    packs = session.get("packs") if isinstance(session.get("packs"), list) else []
    quote_pool = session.get("quote_pool") if isinstance(session.get("quote_pool"), list) else []

    try:
        draft_in = parse_draft_in(draft)
    except (ValidationError, ValueError) as exc:
        # Malformed draft JSON/schema is not model-retryable; deliver machine_failed.
        logger.exception("finalize draft schema failed")
        errors = [str(exc)]
        result = failure_result(errors[0], packs=packs)
        return deliver_result(
            runtime=runtime,
            tool_call_id=tool_call_id,
            result=result,
            ok=False,
            errors=errors,
        )

    try:
        assembled = assemble_draft(session, draft_in.model_dump(exclude_none=True))
        source = session.get("sections") or []
        result, outcome = finalize_review(
            assembled,
            evidence_packs=packs,
            retrieval_empty=bool(session.get("retrieval_empty")),
            strict=True,
            source_sections=source if isinstance(source, list) else [],
        )
        if not allow_retry and outcome.status != "pass":
            return deliver_result(
                runtime=runtime,
                tool_call_id=tool_call_id,
                result=result,
                ok=False,
                errors=outcome.errors,
                warnings=outcome.warnings,
            )
        return finalize_gate(
            runtime=runtime,
            tool_call_id=tool_call_id,
            result=result,
            ok=outcome.status == "pass",
            errors=outcome.errors,
            warnings=outcome.warnings,
            allowed_refs=allowed_refs,
            quote_pool=quote_pool,
        )
    except Exception as exc:
        logger.exception("finalize failed")
        result = failure_result(str(exc), packs=packs)
        if not allow_retry:
            return deliver_result(
                runtime=runtime,
                tool_call_id=tool_call_id,
                result=result,
                ok=False,
                errors=[str(exc)],
            )
        return finalize_gate(
            runtime=runtime,
            tool_call_id=tool_call_id,
            result=result,
            ok=False,
            errors=[str(exc)],
            allowed_refs=allowed_refs,
            quote_pool=quote_pool,
        )
