"""legal-review.v1 Pydantic contract — single source of truth for policy review output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LEGAL_REVIEW_V1 = "legal-review.v1"

RiskLevel = Literal["high", "medium", "low", "none"]
ConfidenceLevel = Literal["high", "medium", "low"]
ReviewStatus = Literal[
    "draft",
    "pending",
    "machine_passed",
    "machine_failed",
    "in_review",
    "approved",
    "rejected",
]
HumanReviewStatus = Literal["required", "not_required", "pending", "approved", "rejected"]
ValidationStatus = Literal["pass", "fail", "skipped", "pending"]
RefusalReason = Literal["empty_retrieval", "insufficient_evidence", "policy"]
EditOp = Literal["replace", "insert_before", "insert_after", "none"]


class StrictModel(BaseModel):
    """Reject unknown keys so Web clients never see undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class Citation(StrictModel):
    """Grounding key is ``id`` only; display fields are enriched server-side."""

    id: str
    citable_as: str | None = None
    doc_id: str | None = None
    page_no: int | None = None
    heading_path: str | None = None


class FindingEvidence(StrictModel):
    """``quote`` must be contiguous source text for Web locate/highlight."""

    quote: str = Field(min_length=1)


class FindingEdit(StrictModel):
    """Deterministic body edit for business Web; not an accept/reject state."""

    op: EditOp = "none"
    text: str | None = None

    @model_validator(mode="after")
    def text_required_when_applicable(self) -> FindingEdit:
        if self.op != "none" and not (self.text or "").strip():
            raise ValueError("edit.text is required when edit.op is not none")
        if self.op == "none":
            self.text = None
        return self


class Finding(StrictModel):
    id: str
    section: str
    risk: RiskLevel
    confidence: ConfidenceLevel
    text: str
    suggestion: str | None = None
    evidence: FindingEvidence
    edit: FindingEdit | None = None
    citations: list[Citation] = Field(default_factory=list)
    parties: list[str] | None = None

    @model_validator(mode="after")
    def high_needs_suggestion(self) -> Finding:
        if self.risk == "high" and not (self.suggestion or "").strip():
            raise ValueError("high-risk finding requires suggestion")
        return self


class Dimension(StrictModel):
    id: str
    name: str
    # Optional in drafts; finalize/normalize derives from findings when omitted.
    risk: RiskLevel | None = None
    findings: list[Finding] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_risk_from_findings(self) -> Dimension:
        if self.risk is None:
            self.risk = dimension_risk(self)
        return self


class Reference(StrictModel):
    """Cited evidence with source text so a reader can verify each citation."""

    id: str
    citable_as: str | None = None
    title: str | None = None
    snippet: str | None = None
    source: str | None = None
    kind: str | None = None
    doc_id: str | None = None
    page_no: int | None = None
    heading_path: str | None = None


class Audit(StrictModel):
    trace_id: str = ""
    knowledge_version: str = ""
    spaces_queried: list[str] = Field(default_factory=list)
    allowed_refs: list[str] = Field(default_factory=list)
    pipeline_stages: list[str] = Field(default_factory=list)


class HumanReview(StrictModel):
    status: HumanReviewStatus


class ValidationBlock(StrictModel):
    status: ValidationStatus
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Refusal(StrictModel):
    reason: RefusalReason
    detail: str | None = None


class LegalReviewDraft(StrictModel):
    """Agent draft — ``report`` is optional; server renders on finalize."""

    schema_hint: str = LEGAL_REVIEW_V1
    mode: str = "full"
    overall_risk: RiskLevel
    review_status: ReviewStatus
    summary: str
    dimensions: list[Dimension]
    audit: Audit
    human_review: HumanReview
    validation: ValidationBlock
    references: list[Reference] = Field(default_factory=list)
    report: str | None = None
    refusal: Refusal | None = None
    next_actions: list[str] | None = None

    @field_validator("schema_hint")
    @classmethod
    def schema_hint_version(cls, value: str) -> str:
        if not value.startswith("legal-review.v"):
            raise ValueError("schema_hint must look like legal-review.v1")
        return value


class LegalReviewV1(LegalReviewDraft):
    """Final deliverable after server finalize (validated + enriched + rendered)."""

    report: str = Field(min_length=1)


class CitationIn(BaseModel):
    """Tool-facing citation — id must be from retrieve allowed_ids."""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, description="Evidence Pack item id from allowed_ids")


class FindingIn(BaseModel):
    """Tool-facing finding. Server merges onto retrieve draft_scaffold."""

    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    section: str | None = None
    risk: RiskLevel
    confidence: ConfidenceLevel = "medium"
    text: str
    suggestion: str | None = None
    evidence: FindingEvidence
    edit: FindingEdit | None = None
    citations: list[CitationIn] = Field(default_factory=list)
    parties: list[str] | None = None
    citation_id: str | None = None
    citation_ids: list[str] | None = None
    evidence_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_finding(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # Flat quote → nested evidence (models often skip the wrapper).
        evidence = data.get("evidence")
        if not isinstance(evidence, dict):
            quote = data.get("quote") or data.get("evidence_quote")
            if isinstance(quote, str) and quote.strip():
                data["evidence"] = {"quote": quote.strip()}
        elif not evidence.get("quote"):
            quote = data.get("quote") or data.get("evidence_quote")
            if isinstance(quote, str) and quote.strip():
                evidence = dict(evidence)
                evidence["quote"] = quote.strip()
                data["evidence"] = evidence

        # Models often put finding prose in aliases or parties{role: note}.
        text = data.get("text")
        if not (isinstance(text, str) and text.strip()):
            for key in (
                "description",
                "content",
                "finding",
                "issue",
                "detail",
                "conclusion",
                "title",
                "message",
            ):
                alt = data.get(key)
                if isinstance(alt, str) and alt.strip():
                    data["text"] = alt.strip()
                    break

        parties = data.get("parties")
        if isinstance(parties, dict):
            if not (isinstance(data.get("text"), str) and str(data["text"]).strip()):
                parts: list[str] = []
                for val in parties.values():
                    if isinstance(val, str) and val.strip():
                        parts.append(val.strip())
                    elif isinstance(val, dict):
                        note = val.get("note") or val.get("text") or val.get("detail")
                        if isinstance(note, str) and note.strip():
                            parts.append(note.strip())
                if parts:
                    data["text"] = "；".join(parts)
            data["parties"] = [str(k).strip() for k in parties if str(k).strip()] or None
        elif isinstance(parties, str) and parties.strip():
            data["parties"] = [parties.strip()]
        elif isinstance(parties, list):
            data["parties"] = [str(x).strip() for x in parties if str(x).strip()] or None

        sug = data.get("suggestion")
        if isinstance(sug, dict):
            data["suggestion"] = str(sug.get("text") or sug.get("summary") or sug.get("content") or "").strip() or None
        elif sug is not None and not isinstance(sug, str):
            data["suggestion"] = str(sug).strip() or None

        fixed: list[dict[str, str]] = []
        seen: set[str] = set()

        def add(raw: Any) -> None:
            if isinstance(raw, dict):
                cid = raw.get("id") or raw.get("citation_id") or raw.get("evidence_id")
            else:
                cid = raw
            if not isinstance(cid, str):
                return
            cid = cid.strip()
            if not cid or cid in seen:
                return
            seen.add(cid)
            fixed.append({"id": cid})

        cites = data.get("citations")
        if isinstance(cites, list):
            for cite in cites:
                add(cite)
        elif isinstance(cites, str):
            add(cites)
        add(data.get("citation_id"))
        add(data.get("evidence_id"))
        ids = data.get("citation_ids")
        if isinstance(ids, list):
            for item in ids:
                add(item)
        data["citations"] = fixed
        return data


class DimensionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    name: str | None = None
    findings: list[FindingIn] = Field(default_factory=list)


class DraftIn(BaseModel):
    """Finalize tool input. Only model-owned fields; harness fills the rest from scaffold."""

    model_config = ConfigDict(extra="ignore")
    summary: str = ""
    dimensions: list[DimensionIn] = Field(default_factory=list)
    overall_risk: RiskLevel | None = None
    mode: str | None = None
    refusal: Refusal | None = None

    @model_validator(mode="before")
    @classmethod
    def promote_flat_findings(cls, data: Any) -> Any:
        """Accept flat findings[] — nested dimensions are hard for tool-calling models."""
        if not isinstance(data, dict):
            return data
        if isinstance(data.get("dimensions"), list) and data["dimensions"]:
            return data
        findings = data.get("findings")
        if not isinstance(findings, list):
            return data
        groups: dict[str, list[Any]] = {}
        for item in findings:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("section") or item.get("dimension") or item.get("dimension_id") or "findings").strip()
            sid = sid or "findings"
            groups.setdefault(sid, []).append(item)
        data["dimensions"] = [{"id": sid, "name": sid, "findings": items} for sid, items in groups.items()]
        return data


def parse_draft(data: dict[str, Any]) -> tuple[LegalReviewDraft | None, list[str]]:
    try:
        return LegalReviewDraft.model_validate(data), []
    except Exception as exc:
        return None, [str(exc)]


RISK_ORDER: dict[str, int] = {"high": 3, "medium": 2, "low": 1, "none": 0}


def max_risk(levels: list[str]) -> RiskLevel:
    best: RiskLevel = "none"
    for risk in levels:
        if risk in RISK_ORDER and RISK_ORDER[risk] > RISK_ORDER[best]:
            best = risk  # type: ignore[assignment]
    return best


def dimension_risk(dim: Dimension) -> RiskLevel:
    return max_risk([finding.risk for finding in dim.findings])


def overall_risk_from_dimensions(dimensions: list[Dimension]) -> RiskLevel:
    return max_risk([dim.risk if dim.risk else dimension_risk(dim) for dim in dimensions])


def machine_failed_result(
    *,
    detail: str,
    packs: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Minimal legal-review.v1 payload for hard failures (parse / flow abort)."""
    first = next((p for p in (packs or []) if isinstance(p, dict)), {}) or {}
    detail_text = str(detail or "").strip() or "预审未能完成"
    return {
        "schema_hint": LEGAL_REVIEW_V1,
        "mode": "full",
        "overall_risk": "none",
        "review_status": "machine_failed",
        "summary": "本轮机器预审未形成可交付结论，请根据校验说明处理后重试。",
        "dimensions": [],
        "audit": {
            "trace_id": str(first.get("trace_id") or ""),
            "knowledge_version": str(first.get("knowledge_version") or ""),
            "spaces_queried": [],
            "allowed_refs": [],
            "pipeline_stages": ["prepare", "retrieve", "draft", "finalize"],
        },
        "human_review": {"status": "required"},
        "validation": {
            "status": "fail",
            "errors": [detail_text],
            "warnings": [],
        },
        "references": [],
        "refusal": None,
        "report": "",
        "next_actions": list(next_actions or ["按校验说明补齐材料后重新预审", "必要时转人工法务复核"]),
    }
