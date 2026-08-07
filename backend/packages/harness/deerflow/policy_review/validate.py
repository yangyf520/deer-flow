"""Grounding and business-rule validation for legal-review.v1."""

from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher
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
# Models truncate with mixed ellipsis styles; normalize for grounding, not display.
ELLIPSIS_RE = re.compile(r"\.{2,}|…+")
FULLWIDTH_PUNCT = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "《": "<",
        "》": ">",
        "、": ",",
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
    }
)
# Do not split on `.` — it breaks section ids like §3.5 and 1.2.a.
SENTENCE_SPLIT = re.compile(r"(?<=[。！？；;])\s*")


def normalize_quote(text: str) -> str:
    """Strip markdown emphasis/escapes/whitespace for grounding comparisons."""
    text = MD_ESCAPE_RE.sub(r"\1", text)
    text = MD_MARKER_RE.sub("", text)
    text = ELLIPSIS_RE.sub("", text)
    text = text.translate(FULLWIDTH_PUNCT)
    return WS_RE.sub("", text)


def _section_matches(hint: str | None, section_id: str) -> bool:
    if not hint or not section_id:
        return True
    hint = hint.strip()
    sid = section_id.strip()
    if hint in sid or sid in hint:
        return True
    hint_norm = normalize_quote(hint)
    sid_norm = normalize_quote(sid)
    return bool(hint_norm and sid_norm and (hint_norm in sid_norm or sid_norm in hint_norm))


def _quote_score(
    needle: str,
    candidate: str,
    *,
    text_hint: str = "",
    min_ratio: float = 0.35,
    min_block: int | None = None,
) -> int:
    """Score how well candidate matches model quote (+ optional finding text)."""
    needle_norm = normalize_quote(needle)
    cand_norm = normalize_quote(candidate)
    if not needle_norm or not cand_norm:
        return 0
    if needle_norm in cand_norm:
        return len(needle_norm) * 1000 + len(cand_norm)
    if cand_norm in needle_norm:
        return len(cand_norm) * 1000
    block_floor = min_block if min_block is not None else max(8, len(needle_norm) // 4)
    best = 0
    for left in (needle_norm + normalize_quote(text_hint), needle_norm):
        if not left:
            continue
        match = SequenceMatcher(None, left, cand_norm).find_longest_match(0, len(left), 0, len(cand_norm))
        if match.size < block_floor:
            continue
        coverage = match.size / max(len(needle_norm), 1)
        ratio = SequenceMatcher(None, left, cand_norm).ratio()
        if coverage >= min_ratio or ratio >= min_ratio:
            best = max(best, int(max(coverage, ratio) * 10000) + match.size)
    return best


def _body_quotes(body: str, *, cap: int = 16) -> list[str]:
    text = (body or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in SENTENCE_SPLIT.split(text) if p and p.strip()]
    if not parts:
        parts = [text]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        candidate = part if len(part) <= 280 else part[:280]
        key = normalize_quote(candidate)
        if len(key) < 8 or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= cap:
            break
    return out


def _section_quote_candidates(body: str) -> list[str]:
    """Contiguous spans from section body for quote grounding."""
    text = (body or "").strip()
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) >= 8:
            key = normalize_quote(stripped)
            if key not in seen:
                seen.add(key)
                out.append(stripped if len(stripped) <= 280 else stripped[:280])
    for cand in _body_quotes(text, cap=24):
        key = normalize_quote(cand)
        if key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def _best_quote(
    quote: str,
    *,
    section_hint: str | None,
    text_hint: str = "",
    source_sections: list[dict[str, Any]],
    quote_pool: list[dict[str, Any]] | None,
    relaxed: bool = False,
) -> str | None:
    if not normalize_quote(quote):
        return None

    min_ratio = 0.28 if relaxed else 0.35
    min_block = max(6, len(normalize_quote(quote)) // 5) if relaxed else None
    candidates: list[tuple[int, int, str]] = []

    def consider(candidate: str, section_id: str = "", *, enforce_section: bool) -> None:
        cleaned = candidate.strip()
        if not cleaned:
            return
        if enforce_section and section_hint and section_id and not _section_matches(section_hint, section_id):
            return
        if quote_matches(cleaned, source_sections) == 0:
            return
        score = _quote_score(
            quote,
            cleaned,
            text_hint=text_hint,
            min_ratio=min_ratio,
            min_block=min_block,
        )
        if score <= 0:
            return
        if enforce_section and section_hint and section_id and _section_matches(section_hint, section_id):
            score += 100_000
        candidates.append((score, len(cleaned), cleaned))

    pool_entries = [entry for entry in (quote_pool or []) if isinstance(entry, dict)]
    for entry in pool_entries:
        sid = str(entry.get("section_id") or "")
        quotes = entry.get("quotes")
        if not isinstance(quotes, list):
            continue
        for pool_q in quotes:
            if isinstance(pool_q, str):
                consider(pool_q, section_id=sid, enforce_section=not relaxed)

    if not candidates or relaxed:
        for entry in pool_entries:
            sid = str(entry.get("section_id") or "")
            quotes = entry.get("quotes")
            if not isinstance(quotes, list):
                continue
            for pool_q in quotes:
                if isinstance(pool_q, str):
                    consider(pool_q, section_id=sid, enforce_section=False)

    for section in source_sections:
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or section.get("title") or "")
        body = str(section.get("body") or "")
        for cand in _section_quote_candidates(body):
            consider(cand, section_id=sid, enforce_section=not relaxed)

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], -item[1]))
    return candidates[0][2]


def quote_is_literal(quote: str, sections: list[dict[str, Any]]) -> bool:
    """True when quote appears verbatim in a section body."""
    cleaned = quote.strip()
    if not cleaned:
        return False
    for section in sections:
        if not isinstance(section, dict):
            continue
        body = str(section.get("body") or "")
        if cleaned in body:
            return True
    return False


def _quote_repairable(needle: str, candidate: str, *, text_hint: str = "", min_ratio: float = 0.35) -> bool:
    """True when candidate is a defensible repair for the model-supplied quote."""
    needle_norm = normalize_quote(needle)
    cand_norm = normalize_quote(candidate)
    if not needle_norm or not cand_norm:
        return False
    if needle_norm in cand_norm or cand_norm in needle_norm:
        return True
    limit = min(len(needle_norm), len(cand_norm))
    prefix = 0
    while prefix < limit and needle_norm[prefix] == cand_norm[prefix]:
        prefix += 1
    if prefix >= max(8, len(needle_norm) // 3):
        return True
    hint_norm = normalize_quote(text_hint)
    combined = needle_norm + hint_norm if hint_norm else needle_norm
    ratio = max(
        SequenceMatcher(None, needle_norm, cand_norm).ratio(),
        SequenceMatcher(None, combined, cand_norm).ratio(),
    )
    return ratio >= min_ratio


def repair_quotes(
    result: dict[str, Any],
    *,
    source_sections: list[dict[str, Any]],
    quote_pool: list[dict[str, Any]] | None = None,
    relaxed: bool = False,
) -> int:
    """Repair paraphrased or truncated evidence.quote using quote_pool / source text."""
    repaired = 0
    for _, finding in iter_findings(result):
        evidence = finding.get("evidence")
        if not isinstance(evidence, dict):
            continue
        quote = str(evidence.get("quote") or "").strip()
        if not quote:
            continue
        grounded = quote_matches(quote, source_sections) > 0
        literal = quote_is_literal(quote, source_sections)
        if grounded and literal:
            continue
        section_hint = str(finding.get("section") or "").strip() or None
        text_hint = str(finding.get("text") or "").strip()
        canonical = _best_quote(
            quote,
            section_hint=section_hint,
            text_hint=text_hint,
            source_sections=source_sections,
            quote_pool=quote_pool,
            relaxed=relaxed,
        )
        if not canonical or canonical == quote:
            continue
        if quote_matches(canonical, source_sections) == 0:
            continue
        if not quote_is_literal(canonical, source_sections):
            continue
        min_ratio = 0.28 if relaxed else 0.35
        if not _quote_repairable(quote, canonical, text_hint=text_hint, min_ratio=min_ratio):
            continue
        evidence["quote"] = canonical
        repaired += 1
    return repaired


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
