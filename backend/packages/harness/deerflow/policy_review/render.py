"""Render deterministic Markdown from a legal-review.v1 result."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

REPORT_TITLE = "制度预审报告"
RISK_LABEL = {"high": "高", "medium": "中", "low": "低", "none": "无"}
RISK_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
STATUS_LABEL = {
    "machine_passed": "机器预审通过",
    "machine_failed": "机器预审未通过",
    "approved": "已批准",
    "rejected": "已拒绝",
    "pending": "待处理",
}
HUMAN_LABEL = {
    "required": "需人工复核",
    "not_required": "暂不要求人工复核",
    "pending": "人工复核中",
    "approved": "人工已批准",
    "rejected": "人工已驳回",
}
EDIT_LABEL = {
    "replace": "替换原文",
    "insert_before": "在原文前插入",
    "insert_after": "在原文后插入",
}
SECTION_CN = ("一", "二", "三", "四", "五", "六", "七", "八")
ERROR_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"needs citation id|citation id\(s\)|overall_risk=high requires", re.I),
        "高/中风险结论缺少制度依据引用：每条中高风险发现须绑定知识库证据编号。",
    ),
    (
        re.compile(r"requires suggestion|high-risk finding requires suggestion", re.I),
        "高风险发现缺少整改建议：请补充可执行的整改说明。",
    ),
    (
        re.compile(r"quote not found|requires a unique", re.I),
        "原文摘录无法在被审稿中唯一定位：请使用连续且唯一的原文片段。",
    ),
    (
        re.compile(r"hallucinated citation|not in allowed_ids", re.I),
        "引用了本轮检索结果之外的依据编号：只能引用本次召回的证据。",
    ),
    (
        re.compile(r"source_sections are required", re.I),
        "缺少被审稿原文，无法完成引用与改文锚定校验。",
    ),
    (
        re.compile(r"pipeline_stages missing", re.I),
        "预审流程阶段不完整，结果未达到可交付状态。",
    ),
    (
        re.compile(r"invalid JSON|must be a JSON object|draft is empty|trailing garbage|JSONDecodeError|char \d+", re.I),
        "审查草稿格式无效，请重新发起预审。",
    ),
    (
        re.compile(r"Field required|\.text:|findings\.\d+\.text", re.I),
        "发现项缺少完整说明，请补充结论描述后重新预审。",
    ),
    (
        re.compile(r"Policy review incomplete|before policy_finalize|reminders|next expected", re.I),
        "预审流程未完成，尚未形成可交付结论；请重新发起预审。",
    ),
    (
        re.compile(r"policy_prepare|policy_retrieve|policy_finalize", re.I),
        "预审步骤未按完整流程执行，请重新发起预审。",
    ),
]

CONFIDENCE_LABEL = {"high": "高", "medium": "中", "low": "低"}
MODE_LABEL = {"full": "完整预审", "quick": "快速预审", "delta": "差异预审"}
PARTY_LABEL = {
    "legal": "法务",
    "security": "安全",
    "privacy": "隐私",
    "compliance": "合规",
    "it": "IT",
    "business": "业务",
    "product": "产品",
}
MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.M)
MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
MD_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M)
MD_FENCE_RE = re.compile(r"```[\s\S]*?```")
WS_RE = re.compile(r"\s+")


def format_citation(cite: dict[str, Any]) -> str:
    label = cite.get("citable_as") or cite.get("title") or cite.get("id") or "未标注依据"
    parts = [str(label)]
    if cite.get("heading_path"):
        parts.append(str(cite["heading_path"]))
    if cite.get("page_no") is not None:
        parts.append(f"第 {cite['page_no']} 页")
    return " · ".join(parts)


def sanitize_snippet(text: str, *, limit: int = 120) -> str:
    """Strip KB markdown noise so snippets cannot become fake report headings/tables."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = MD_FENCE_RE.sub(" ", raw)
    raw = MD_TABLE_SEP_RE.sub(" ", raw)
    raw = MD_TABLE_ROW_RE.sub(" ", raw)
    raw = MD_HEADING_RE.sub("", raw)
    raw = raw.replace("|", " ")
    raw = WS_RE.sub(" ", raw).strip(" -•…")
    if len(raw) <= limit:
        return raw
    return raw[:limit].rstrip(" ，,;；") + "…"


def findings_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for dim in result.get("dimensions") or []:
        if isinstance(dim, dict):
            findings.extend(item for item in dim.get("findings") or [] if isinstance(item, dict))
    return findings


def risk_rank(value: Any) -> int:
    return RISK_ORDER.get(str(value or "none"), 9)


def humanize_error(error: str) -> str:
    text = str(error or "").strip()
    if not text:
        return ""
    for pattern, label in ERROR_RULES:
        if pattern.search(text):
            return label
    cleaned = re.sub(r"\$\.[a-zA-Z0-9_\[\]\.]+:\s*", "", text).strip()
    cleaned = re.sub(
        r"\b(draft|dimensions|findings|citations|evidence|validation|schema_hint|review_status)\b[^\s，。；]*",
        "",
        cleaned,
        flags=re.I,
    ).strip(" :-")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if not cleaned or re.search(r"[A-Za-z_]{3,}", cleaned):
        return "预审结果未通过机器校验，请按报告说明处理后重新预审。"
    return cleaned


def disposition(overall: str, *, passed: bool, high_count: int, medium_count: int) -> str:
    if not passed:
        return "不得作为对外签发或自动改文依据；须按校验说明补齐后重新预审，并视情况转人工复核。"
    if overall == "high" or high_count:
        return "建议退回业务方整改后再送审；高风险项须完成制度依据对齐，并提交人工法务 / 隐私 / 安全终审。"
    if overall == "medium" or medium_count:
        return "可通过机器预审，但须在限期内完成中风险整改；建议安排人工抽检后进入下一流程。"
    if overall == "low":
        return "机器预审未见高/中风险阻断项；可进入下一流程，保留低风险项跟踪与抽检。"
    return "机器预审未见需披露风险项；可进入下一流程，仍不替代人工终审。"


def sorted_dimensions(dimensions: list[Any]) -> list[dict[str, Any]]:
    dims = [d for d in dimensions if isinstance(d, dict)]

    def dim_key(dim: dict[str, Any]) -> tuple[int, str]:
        findings = [f for f in (dim.get("findings") or []) if isinstance(f, dict)]
        best = min((risk_rank(f.get("risk")) for f in findings), default=risk_rank(dim.get("risk")))
        return best, str(dim.get("name") or dim.get("id") or "")

    dims.sort(key=dim_key)
    return dims


def sorted_findings(findings: list[Any]) -> list[dict[str, Any]]:
    items = [f for f in findings if isinstance(f, dict)]
    items.sort(key=lambda f: (risk_rank(f.get("risk")), str(f.get("id") or "")))
    return items


def party_label(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    return PARTY_LABEL.get(text.lower(), text)


def escape_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def cite_labels(finding: dict[str, Any]) -> list[str]:
    cites = finding.get("citations")
    if not isinstance(cites, list):
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for cite in cites:
        if isinstance(cite, dict):
            label = format_citation(cite)
        elif isinstance(cite, str) and cite.strip():
            label = cite.strip()
        else:
            continue
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def unique_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by citable_as/title so the same policy doc is listed once."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in references:
        if not isinstance(ref, dict):
            continue
        key = str(ref.get("citable_as") or ref.get("title") or ref.get("id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def render_report(result: dict[str, Any]) -> str:
    """Human-facing professional GFM report. JSON remains the Web payload."""
    overall = str(result.get("overall_risk") or "none")
    status = str(result.get("review_status") or "")
    summary = str(result.get("summary") or "").strip()
    findings = findings_of(result)
    counts = {risk: sum(item.get("risk") == risk for item in findings) for risk in RISK_LABEL}
    passed = status == "machine_passed"
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
    human = result.get("human_review") if isinstance(result.get("human_review"), dict) else {}
    human_status = str(human.get("status") or "not_required")
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    spaces = ", ".join(str(x) for x in (audit.get("spaces_queried") or []) if str(x).strip())
    allowed_n = len(audit.get("allowed_refs") or []) if isinstance(audit.get("allowed_refs"), list) else 0
    advice = disposition(overall, passed=passed, high_count=counts["high"], medium_count=counts["medium"])

    section = 0

    def heading(title: str) -> str:
        nonlocal section
        label = SECTION_CN[section] if section < len(SECTION_CN) else str(section + 1)
        section += 1
        return f"## {label}、{title}"

    lines = [
        f"# {REPORT_TITLE}",
        "",
        "| 项目 | 内容 |",
        "| --- | --- |",
        f"| 预审结论 | **{STATUS_LABEL.get(status, status or '未知')}** |",
        f"| 总体风险 | **{RISK_LABEL.get(overall, overall)}**（高 {counts['high']} / 中 {counts['medium']} / 低 {counts['low']} / 提示 {counts['none']}） |",
        f"| 处置建议 | {advice} |",
        f"| 生成时间 | {generated_at} |",
        f"| 审查范围 | {MODE_LABEL.get(str(result.get('mode') or 'full'), '完整预审')} |",
        f"| 预审流水号 | {audit.get('trace_id') or '未生成'} |",
        f"| 检索知识空间 | {spaces or '按智能体绑定空间'} |",
        f"| 可用制度依据 | {allowed_n} 条 |",
        f"| 人工复核 | {HUMAN_LABEL.get(human_status, human_status)} |",
    ]

    lines.extend(["", heading("审查摘要"), ""])
    if summary and not summary.lower().startswith("invalid json"):
        # Prefer bullets over a long prose blob that restates findings.
        bullets = [part.strip(" ；;。") for part in re.split(r"[；;]\s*", summary) if part.strip()]
        if len(bullets) >= 2:
            lines.extend(f"- {item}。" if not item.endswith(("。", "！", "？")) else f"- {item}" for item in bullets)
        else:
            lines.append(summary)
    elif findings:
        for finding in sorted_findings(findings)[:8]:
            risk = str(finding.get("risk") or "none")
            text = str(finding.get("text") or "").strip()
            if text:
                lines.append(f"- [{RISK_LABEL.get(risk, risk)}] {text}")
    elif not passed:
        lines.append("本轮未能形成可交付的完整审查结论，详见校验说明。")
    else:
        lines.append("未见需披露风险项。")

    validation = result.get("validation")
    if isinstance(validation, dict) and validation.get("status") == "fail":
        raw_errors = [str(item).strip() for item in validation.get("errors") or [] if str(item).strip()]
        human_errors: list[str] = []
        seen: set[str] = set()
        for error in raw_errors:
            label = humanize_error(error)
            if label and label not in seen:
                seen.add(label)
                human_errors.append(label)
        lines.extend(["", heading("校验说明"), "", "本轮结果**未通过机器校验**，不得作为自动改文或对外签发依据。"])
        if human_errors:
            lines.extend(["", *[f"- {item}" for item in human_errors]])

    refusal = result.get("refusal")
    if isinstance(refusal, dict) and refusal.get("reason"):
        reason = str(refusal.get("reason") or "")
        reason_label = {
            "empty_retrieval": "未检索到可用制度依据",
            "insufficient_evidence": "证据不足，无法支持定罪式结论",
            "policy": "按策略停止审查",
        }.get(reason, reason)
        lines.extend(["", heading("无法完成实质审查"), ""])
        lines.append(f"- **原因**：{reason_label}")
        if refusal.get("detail"):
            detail = humanize_error(str(refusal["detail"]))
            if detail:
                lines.append(f"- **说明**：{detail}")

    if findings:
        lines.extend(
            [
                "",
                heading("风险明细"),
                "",
                "| # | 风险 | 定位 | 结论 | 依据 | 整改要求 |",
                "| ---: | --- | --- | --- | --- | --- |",
            ]
        )
        for index, finding in enumerate(sorted_findings(findings), 1):
            item_risk = str(finding.get("risk") or "none")
            title = escape_cell(finding.get("text") or finding.get("id") or f"发现项 {index}")
            section_name = escape_cell(finding.get("section") or "未标注")
            cites = cite_labels(finding)
            cite_cell = escape_cell("；".join(cites) if cites else ("—" if item_risk not in ("high", "medium") else "缺依据"))
            suggestion = escape_cell(finding.get("suggestion") or "—")
            lines.append(f"| {index} | {RISK_LABEL.get(item_risk, item_risk)} | {section_name} | {title} | {cite_cell} | {suggestion} |")

        lines.extend(["", heading("原文与依据（按发现项）")])
        for index, finding in enumerate(sorted_findings(findings), 1):
            item_risk = str(finding.get("risk") or "none")
            title = str(finding.get("text") or finding.get("id") or f"发现项 {index}").strip()
            lines.extend(["", f"### {index}. [{RISK_LABEL.get(item_risk, item_risk)}风险] {title}", ""])
            meta_bits = [
                f"**定位**：{finding.get('section') or '未标注'}",
                f"**置信度**：{CONFIDENCE_LABEL.get(str(finding.get('confidence') or ''), finding.get('confidence') or '未标注')}",
            ]
            parties = finding.get("parties")
            if isinstance(parties, list) and parties:
                labels = [party_label(item) for item in parties if party_label(item)]
                if labels:
                    meta_bits.append(f"**责任主体**：{'、'.join(labels)}")
            lines.append("- " + " · ".join(meta_bits))

            evidence = finding.get("evidence")
            quote = str(evidence.get("quote") or "").strip() if isinstance(evidence, dict) else ""
            if quote:
                lines.extend(["- **原文**：", "", f"> {sanitize_snippet(quote, limit=240)}"])

            cites = cite_labels(finding)
            if cites:
                lines.append("- **依据**：")
                lines.extend(f"  - {item}" for item in cites)
            elif item_risk in ("high", "medium"):
                lines.append("- **依据**：_尚未绑定有效依据，不得视为已证实违规。_")

            suggestion = str(finding.get("suggestion") or "").strip()
            if suggestion:
                lines.append(f"- **整改**：{suggestion}")

            edit = finding.get("edit")
            if isinstance(edit, dict):
                op = str(edit.get("op") or "none")
                text = str(edit.get("text") or "").strip()
                if op in EDIT_LABEL and text:
                    lines.extend([f"- **建议改文（{EDIT_LABEL[op]}）**：", "", f"> {sanitize_snippet(text, limit=280)}"])

    lines.extend(["", heading("后续建议"), ""])
    actions = [str(item).strip() for item in result.get("next_actions") or [] if str(item).strip()]
    human_actions = [action for action in actions if not action.lower().startswith("fix draft") and "policy_finalize" not in action.lower()]
    if human_actions:
        lines.extend(f"- [ ] {action}" for action in human_actions)
    elif not passed:
        lines.extend(
            [
                "- [ ] 按校验说明补齐依据与整改建议后，重新提交预审",
                "- [ ] 高风险项组织人工法务 / 隐私 / 安全复核",
            ]
        )
    elif counts["high"]:
        lines.extend(
            [
                "- [ ] 退回业务方完成高风险整改并附制度依据",
                "- [ ] 整改完成后提交人工终审",
            ]
        )
    elif counts["medium"]:
        lines.extend(
            [
                "- [ ] 限期内完成中风险整改",
                "- [ ] 安排人工抽检后进入下一流程",
            ]
        )
    else:
        lines.extend(
            [
                "- [ ] 可进入下一业务流程",
                "- [ ] 保留抽检与人工终审权利",
            ]
        )

    references = unique_references([r for r in (result.get("references") or []) if isinstance(r, dict)])
    if references:
        lines.extend(
            [
                "",
                heading("引证依据"),
                "",
                "| # | 依据 | 定位 | 摘录 |",
                "| ---: | --- | --- | --- |",
            ]
        )
        for i, ref in enumerate(references, 1):
            label = escape_cell(ref.get("citable_as") or ref.get("title") or ref.get("id") or f"依据 {i}")
            locus = escape_cell(
                " · ".join(
                    str(part)
                    for part in (
                        ref.get("heading_path"),
                        f"第 {ref['page_no']} 页" if ref.get("page_no") is not None else None,
                    )
                    if part
                )
                or "—"
            )
            snippet = escape_cell(sanitize_snippet(str(ref.get("snippet") or ""), limit=100) or "—")
            lines.append(f"| {i} | {label} | {locus} | {snippet} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "_本报告由机器预审生成，每条风险结论须有被审稿原文与制度依据支撑；不替代人工法务、隐私或安全终审，不得单独作为对外法律意见。_",
        ]
    )
    return "\n".join(lines).strip() + "\n"
