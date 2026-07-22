"""Grounding and business-rule validation for legal-review.v1."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from deerflow.policy_review.contract import (
    LEGAL_REVIEW_V1,
    dimension_risk,
    overall_risk_from_dimensions,
    parse_draft,
)

CORE_PIPELINE_STAGES = ("prepare", "retrieve", "draft", "validate", "deliver")

# Docling markdown export carries formatting noise (bold/italic markers,
# backslash-escaped punctuation, reflowed line breaks) that the model does not
# reproduce when it quotes plain source text. Normalize both sides so quote
# grounding is robust without weakening it.
MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
MD_MARKER_RE = re.compile(r"[*`]+")
WS_RE = re.compile(r"\s+")


def normalize_quote(text: str) -> str:
    """Strip markdown emphasis/escapes/whitespace for grounding comparisons."""
    text = MD_ESCAPE_RE.sub(r"\1", text)
    text = MD_MARKER_RE.sub("", text)
    return WS_RE.sub("", text)


def iter_findings(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    dims = result.get("dimensions")
    if isinstance(dims, list):
        for di, dim in enumerate(dims):
            if not isinstance(dim, dict):
                continue
            findings = dim.get("findings")
            if not isinstance(findings, list):
                continue
            for fi, finding in enumerate(findings):
                if isinstance(finding, dict):
                    out.append((f"$.dimensions[{di}].findings[{fi}]", finding))
    top = result.get("findings")
    if isinstance(top, list):
        for fi, finding in enumerate(top):
            if isinstance(finding, dict):
                out.append((f"$.findings[{fi}]", finding))
    return out


def collect_citation_ids(node: Any, path: str = "$") -> list[tuple[str, str]]:
    """Return (json_path, citation_id) for grounding checks."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}"
            if key == "citations" and isinstance(value, list):
                for i, item in enumerate(value):
                    item_path = f"{child}[{i}]"
                    if isinstance(item, dict):
                        cid = item.get("id")
                        if isinstance(cid, str) and cid.strip():
                            found.append((f"{item_path}.id", cid.strip()))
                    elif isinstance(item, str) and item.strip():
                        found.append((item_path, item.strip()))
            else:
                found.extend(collect_citation_ids(value, child))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found.extend(collect_citation_ids(item, f"{path}[{i}]"))
    return found


def allowed_ids_from_packs(packs: Iterable[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for pack in packs:
        items = pack.get("items") if isinstance(pack, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                iid = item.get("id")
                if isinstance(iid, str) and iid.strip():
                    ids.add(iid.strip())
    return ids


def finding_has_citations(finding: dict[str, Any]) -> bool:
    cites = finding.get("citations")
    if not isinstance(cites, list) or not cites:
        return False
    for item in cites:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            return True
        if isinstance(item, str) and item.strip():
            return True
    return False


def quote_matches(quote: str, sections: list[dict[str, Any]]) -> int:
    """Count quote occurrences per section, ignoring markdown formatting noise."""
    needle = normalize_quote(quote)
    if not needle:
        return 0
    return sum(normalize_quote(str(section.get("body") or "")).count(needle) for section in sections if isinstance(section, dict))


def validate_review(
    result: Any,
    allowed_ids: set[str] | None = None,
    *,
    strict: bool = False,
    retrieval_empty: bool = False,
    source_sections: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate draft/final JSON. Grounding uses Evidence Pack ``id`` only."""
    errors: list[str] = []
    warnings: list[str] = []

    def bump(msg: str, *, as_error: bool = False) -> None:
        if as_error or strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    if not isinstance(result, dict):
        return ["result root must be a JSON object"], warnings

    if strict and source_sections is None:
        errors.append("source_sections are required for strict quote validation")

    review_status = result.get("review_status")
    validation = result.get("validation", {}) if isinstance(result.get("validation"), dict) else {}
    is_draft = review_status == "draft" or validation.get("status") == "skipped"

    if is_draft:
        if review_status != "draft":
            errors.append("draft output must set review_status=draft")
        if validation.get("status") != "skipped":
            errors.append("draft output must set validation.status=skipped")
        return errors, warnings

    draft, schema_errors = parse_draft(result)
    errors.extend(schema_errors)

    hint = result.get("schema_hint")
    if hint is not None and hint != LEGAL_REVIEW_V1:
        bump(f"schema_hint {hint!r} should be {LEGAL_REVIEW_V1!r}")

    audit = result.get("audit") if isinstance(result.get("audit"), dict) else None
    if audit is None:
        bump("audit block missing; need trace_id, knowledge_version, pipeline_stages")
    else:
        if not audit.get("trace_id"):
            bump("audit.trace_id empty; copy from search Evidence Pack")
        if not audit.get("knowledge_version"):
            bump("audit.knowledge_version empty; copy from search Evidence Pack")
        stages = audit.get("pipeline_stages")
        if not isinstance(stages, list) or not stages:
            bump(f"audit.pipeline_stages missing; use [{', '.join(CORE_PIPELINE_STAGES)}]")
        else:
            missing = [s for s in CORE_PIPELINE_STAGES[:3] if s not in stages]
            if missing:
                bump(f"audit.pipeline_stages missing core stages {missing}")

    overall = result.get("overall_risk")

    cite_ids = collect_citation_ids(result)
    empty_pack = retrieval_empty or (allowed_ids is not None and len(allowed_ids) == 0)

    dim_ids: set[str] = set()
    dims = result.get("dimensions")
    if isinstance(dims, list):
        for di, dim in enumerate(dims):
            if not isinstance(dim, dict):
                continue
            dim_id = dim.get("id")
            if isinstance(dim_id, str) and dim_id.strip():
                if dim_id in dim_ids:
                    errors.append(f"$.dimensions[{di}].id duplicated: {dim_id!r}")
                dim_ids.add(dim_id)

    finding_ids: set[str] = set()
    for fpath, finding in iter_findings(result):
        fid = finding.get("id")
        if isinstance(fid, str) and fid.strip():
            if fid in finding_ids:
                errors.append(f"{fpath}.id duplicated: {fid!r}")
            finding_ids.add(fid)

    for fpath, finding in iter_findings(result):
        risk = finding.get("risk")
        confidence = finding.get("confidence")
        evidence = finding.get("evidence")
        if not isinstance(evidence, dict) or not str(evidence.get("quote", "")).strip():
            errors.append(f"{fpath}: evidence.quote is required")
        else:
            quote = str(evidence.get("quote") or "")
            if quote != quote.strip():
                errors.append(f"{fpath}: evidence.quote must be contiguous source text (no leading/trailing whitespace)")
        edit = finding.get("edit")
        edit_op = "none"
        if edit is not None:
            if not isinstance(edit, dict):
                errors.append(f"{fpath}: edit must be an object")
            else:
                edit_op = edit.get("op", "none")
                if edit_op not in ("replace", "insert_before", "insert_after", "none"):
                    errors.append(f"{fpath}: edit.op must be replace|insert_before|insert_after|none")
                elif edit_op != "none" and not str(edit.get("text") or "").strip():
                    errors.append(f"{fpath}: edit.text is required when edit.op is not none")
        if source_sections is not None and isinstance(evidence, dict):
            quote = str(evidence.get("quote") or "").strip()
            if quote:
                matches = quote_matches(quote, source_sections)
                if matches == 0:
                    errors.append(f"{fpath}: evidence.quote not found in source sections")
                elif edit_op != "none" and matches != 1:
                    errors.append(f"{fpath}: applicable edit requires a unique evidence.quote; found {matches} matches")
        if risk not in ("high", "medium"):
            continue
        if confidence == "low":
            continue
        if finding_has_citations(finding):
            continue
        msg = f"{fpath}: medium/high risk (confidence≠low) needs citation id(s)" + (" — empty Evidence Pack (refusal / no-convict)" if empty_pack else "")
        errors.append(msg)

    if overall == "high" and not cite_ids:
        errors.append("overall_risk=high requires at least one citation id (or lower overall_risk / draft)")

    if cite_ids:
        if allowed_ids is None:
            errors.append("citations present but allowed_ids not provided; pass Evidence Pack item ids")
        elif not allowed_ids:
            errors.append("citations present but allowed_ids empty; cannot ground against empty Evidence Pack")
        else:
            for json_path, cid in cite_ids:
                if cid not in allowed_ids:
                    errors.append(f"{json_path}: {cid!r} not in allowed_ids (hallucinated citation rejected)")

    if draft is not None:
        computed = overall_risk_from_dimensions(draft.dimensions)
        if draft.overall_risk != computed:
            bump(f"overall_risk={draft.overall_risk!r} disagrees with max(dimensions)={computed!r}")
        for di, dim in enumerate(draft.dimensions):
            computed_dim = dimension_risk(dim)
            if dim.risk != computed_dim:
                bump(f"$.dimensions[{di}].risk={dim.risk!r} disagrees with max(findings)={computed_dim!r}")

    if review_status == "machine_passed" and validation.get("status") != "pass":
        errors.append("review_status=machine_passed requires validation.status=pass")

    if retrieval_empty and not result.get("refusal"):
        bump("retrieval_empty=true but refusal block missing")

    return errors, warnings
