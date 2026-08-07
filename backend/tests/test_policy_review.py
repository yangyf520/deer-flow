"""Tests for deerflow.policy_review (legal-review.v1)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.policy_review.pipeline import (
    build_draft_scaffold,
    build_evidence_digest,
    doc_ids_from_packs,
    empty_section_pack,
    extract_quote_candidates,
    finalize_review,
    looks_like_section_heading,
    merge_sections,
    prepare_sections,
    resolve_policy_review_top_k,
    retrieve_for_sections,
    section_query,
    slim_quote_pool,
    split_markdown_into_sections,
    supplement_missing_space_documents,
)
from deerflow.policy_review.validate import validate_review


def test_section_query_results():
    """Model may re-feed section_results (section_id + query) into retrieve."""
    assert section_query({"section_id": "section-1", "query": "密钥管理\n范围"}) == "密钥管理\n范围"
    assert section_query({"id": "s1", "title": "范围", "body": "正文"}) == "范围\n正文"
    assert section_query({}) == ""


def test_prepare_bold_split(tmp_path, monkeypatch):
    from deerflow.utils.file_conversion import ParseResult

    doc = tmp_path / "prd.docx"
    doc.write_bytes(b"fake-docx")
    long_body = "正文段落。" * 400
    markdown = f"**一、产品背景**\n\n{long_body}\n\n**二、功能需求**\n\n系统应支持算法备案与安全评估。\n\n**三、合规声明**\n\n应提供投诉举报入口。\n"
    monkeypatch.setattr(
        "deerflow.utils.file_conversion.parse_file_bytes_with_fallback",
        lambda _data, _name: (ParseResult(text=markdown, parse_quality="ok"), "markitdown"),
    )

    out = prepare_sections(doc, title="PRD")

    assert out["parse_backend"] == "markitdown"
    assert out["section_count"] >= 3
    titles = [section["title"] for section in out["sections"]]
    assert any("产品背景" in title for title in titles)
    assert any("功能需求" in title for title in titles)


def test_split_bold_headings():
    text = "**一、背景**\n\n第一段。\n\n**1.1 范围**\n\n第二段。\n\n**普通加粗不是标题**\n\n第三段。\n"
    sections = split_markdown_into_sections(text)
    assert len(sections) == 2
    assert sections[0]["title"] == "一、背景"
    assert sections[1]["title"] == "1.1 范围"
    assert "普通加粗不是标题" in sections[1]["body"]


def test_looks_like_section_heading():
    assert looks_like_section_heading("一、产品背景")
    assert looks_like_section_heading("1.1 范围说明")
    assert not looks_like_section_heading("这是一段很长的正文标题不应该被识别为章节标题因为实在太长了")


def test_resolve_top_k():
    assert resolve_policy_review_top_k(None) >= 20
    assert resolve_policy_review_top_k(12) == 12
    assert resolve_policy_review_top_k(100) == 50


def test_doc_ids_from_packs():
    packs = [
        {
            "items": [
                {"id": "a", "metadata": {"doc_id": "doc-a"}},
                {"id": "b", "doc_id": "doc-b"},
            ]
        }
    ]
    assert doc_ids_from_packs(packs) == {"doc-a", "doc-b"}


@pytest.mark.asyncio
async def test_supplement_anchors():
    doc_a = SimpleNamespace(id="doc-a", title="生成式人工智能服务管理暂行办法", source_filename="a.pdf")
    doc_b = SimpleNamespace(id="doc-b", title="中华人民共和国个人信息保护法", source_filename="b.pdf")

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = [doc_a, doc_b]
            return result

    packs = [
        {
            "items": [
                {
                    "id": "ev-1",
                    "metadata": {"doc_id": "doc-a"},
                }
            ]
        }
    ]
    search = AsyncMock(
        side_effect=[
            SimpleNamespace(
                model_dump=lambda: {
                    "items": [{"id": "ev-2", "metadata": {"doc_id": "doc-b"}}],
                    "metadata": {"space_results": []},
                }
            ),
        ]
    )

    with (
        patch(
            "deerflow.knowledge.runtime.resolve_agent_knowledge_scope",
            return_value=(["sense-ri-legal"], "policy-review"),
        ),
        patch("deerflow.knowledge.app.query.search", search),
    ):
        new_packs, section_results = await supplement_missing_space_documents(
            session_factory=lambda: _Session(),
            user_id="u1",
            system_role="user",
            spaces=["sense-ri-legal"],
            scenario="policy-review",
            top_k_per_doc=5,
            packs=list(packs),
            section_results=[],
            sem=asyncio.Semaphore(2),
        )

    assert len(new_packs) == 2
    assert len(section_results) == 1
    assert section_results[0]["section_id"].startswith("anchor-")
    search.assert_awaited_once()


def test_prepare_docling_fallback(tmp_path, monkeypatch):
    from deerflow.utils.file_conversion import ParseResult

    doc = tmp_path / "policy.docx"
    doc.write_bytes(b"fake-docx")

    monkeypatch.setattr(
        "deerflow.utils.file_conversion.parse_file_bytes_with_fallback",
        lambda _data, _name: (ParseResult(text="# 标题\n\n正文", parse_quality="ok"), "markitdown"),
    )

    out = prepare_sections(doc, title="密钥管理 PRD")

    assert out["parse_backend"] == "markitdown"
    assert out["title"] == "密钥管理 PRD"
    assert out["section_count"] >= 1
    assert any("正文" in str(section.get("body") or "") for section in out["sections"])


@pytest.mark.asyncio
async def test_retrieve_skips_empty():
    search = AsyncMock()
    with patch("deerflow.knowledge.app.query.search", search):
        out = await retrieve_for_sections(
            session=MagicMock(),
            user_id="u1",
            system_role="user",
            sections=[{}, {"section_id": "s2", "query": ""}],
        )
    search.assert_not_called()
    assert out["retrieval_empty"] is True
    assert all(r["hit_count"] == 0 for r in out["section_results"])
    assert empty_section_pack(section_id="x")["pack"]["items"] == []


def _minimal_draft(*, cite_id: str | None = "ev-1", overall: str = "low") -> dict:
    citations = [{"id": cite_id}] if cite_id else []
    return {
        "schema_hint": "legal-review.v1",
        "mode": "full",
        "overall_risk": overall,
        "review_status": "pending",
        "summary": "测试摘要",
        "dimensions": [
            {
                "id": "legal",
                "name": "合规",
                "risk": overall,
                "findings": [
                    {
                        "id": "f1",
                        "section": "§1",
                        "risk": overall,
                        "confidence": "high",
                        "text": "发现说明",
                        "suggestion": "建议修改" if overall == "high" else None,
                        "evidence": {"quote": "原文摘录"},
                        "citations": citations,
                    }
                ],
            }
        ],
        "audit": {
            "trace_id": "t1",
            "knowledge_version": "kv1",
            "spaces_queried": ["legal"],
            "pipeline_stages": ["prepare", "retrieve", "draft"],
        },
        "human_review": {"status": "not_required"},
        "validation": {"status": "pending", "errors": [], "warnings": []},
    }


def _pack(ev_id: str = "ev-1") -> dict:
    return {
        "trace_id": "t1",
        "knowledge_version": "kv1",
        "items": [
            {
                "id": ev_id,
                "source": "legal",
                "kind": "regulation",
                "title": "PIPL",
                "snippet": "…",
                "citable_as": "PIPL / 第1条",
                "metadata": {"doc_id": "doc-1", "page_no": 3, "heading_path": "第一章", "space_id": "legal"},
            }
        ],
    }


def _source(body: str = "前文。原文摘录。后文。") -> list[dict]:
    return [{"title": "§1", "body": body}]


class TestPolicyReview:
    """Core finalize + multi-lane retrieve."""

    def test_finalize_grounded(self):
        draft = _minimal_draft()
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        assert result["review_status"] == "machine_passed"
        assert "制度预审报告" in result["report"]
        assert "机器预审通过" in result["report"]
        assert "预审结论" in result["report"]
        assert "风险明细" in result["report"]
        assert "签署与复核" not in result["report"]
        assert "引证依据" in result["report"]
        assert "pending" not in result["report"]
        assert "### 处置结论" not in result["report"]
        assert "风险概览" not in result["report"]
        assert "一、报告信息" not in result["report"]
        assert result["dimensions"][0]["findings"][0]["citations"][0]["citable_as"] == "PIPL / 第1条"
        refs = result["references"]
        assert [r["id"] for r in refs] == ["ev-1"]
        assert refs[0]["citable_as"] == "PIPL / 第1条"
        assert refs[0]["snippet"] == "…"

    def test_spaces_dedupe(self):
        from deerflow.policy_review.pipeline import spaces_from_packs

        packs = [
            {"items": [{"id": "a", "metadata": {"space_id": "legal"}}]},
            {"items": [{"id": "b", "metadata": {"space_id": "legal"}}, {"id": "c", "metadata": {"space_id": "hr"}}]},
            {"items": [{"id": "d", "metadata": {}}]},
        ]
        assert spaces_from_packs(packs) == ["legal", "hr"]

    def test_humanize_errors(self):
        from deerflow.policy_review.render import humanize_error

        assert "发现项缺少完整说明" in humanize_error("$.dimensions[0].findings[0].text: Field required")
        assert "预审流程未完成" in humanize_error("Policy review incomplete: model exited before policy_finalize")
        # Bare JSONPath / English schema noise → generic business label
        assert humanize_error("$.audit.pipeline_stages: value is not a valid list") == ("预审结果未通过机器校验，请按报告说明处理后重新预审。")

    def test_report_sanitize(self):
        from deerflow.policy_review.render import render_report, sanitize_snippet

        dirty = "## 最终产品：\n| 文件名称 | x |\n| --- | --- |\n核心保密数据定义。"
        assert "最终产品" in sanitize_snippet(dirty)
        assert "|" not in sanitize_snippet(dirty)
        assert "##" not in sanitize_snippet(dirty)

        draft = _minimal_draft(overall="high")
        draft["dimensions"][0]["findings"][0]["suggestion"] = "必须整改"
        draft["references"] = [
            {
                "id": "ev-1",
                "citable_as": "PIPL / 第1条",
                "snippet": dirty,
                "page_no": 3,
            },
            {
                "id": "ev-1b",
                "citable_as": "PIPL / 第1条",
                "snippet": "重复同一依据应被折叠",
            },
        ]
        report = render_report(draft)
        assert "| # | 风险 | 定位 | 结论 | 依据 | 整改要求 |" in report
        assert "| # | 依据 | 定位 | 摘录 |" in report
        assert report.count("PIPL / 第1条") >= 1
        assert "最终产品：" not in report or "## 最终产品" not in report
        assert "## 最终产品" not in report
        assert "### 处置结论" not in report

    def test_report_risk_order(self):
        from deerflow.policy_review.render import render_report

        draft = _minimal_draft(overall="high")
        draft["dimensions"][0]["findings"][0]["suggestion"] = "必须整改"
        draft["dimensions"].append(
            {
                "id": "ops",
                "name": "运营",
                "risk": "low",
                "findings": [
                    {
                        "id": "f2",
                        "section": "§2",
                        "risk": "low",
                        "confidence": "high",
                        "text": "低风险提示项",
                        "evidence": {"quote": "原文摘录"},
                        "citations": [{"id": "ev-1"}],
                    }
                ],
            }
        )
        draft["audit"]["trace_id"] = "tr-demo"
        draft["audit"]["knowledge_version"] = "kv-demo"
        draft["audit"]["spaces_queried"] = ["legal"]
        draft["audit"]["allowed_refs"] = ["ev-1"]
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        report = result["report"] or render_report(result)
        assert "tr-demo" in report
        assert "预审流水号" in report
        assert "建议退回业务方整改" in report
        high_pos = report.find("[高风险]")
        low_pos = report.find("[低风险]")
        assert high_pos != -1 and low_pos != -1 and high_pos < low_pos
        # Overview table lists high before detail sections; detail headings keep order.
        assert report.find("| 高 |") != -1 or "总体风险" in report

    def test_finalize_dim_risk(self):
        draft = _minimal_draft(overall="medium")
        del draft["dimensions"][0]["risk"]
        del draft["overall_risk"]
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        assert result["dimensions"][0]["risk"] == "medium"
        assert result["overall_risk"] == "medium"
        assert result["schema_hint"] == "legal-review.v1"

    def test_finalize_normalize_ids(self):
        draft = _minimal_draft(overall="low")
        dim = draft["dimensions"][0]
        del dim["id"]
        dim["name"] = "数据分类"
        dim["title"] = "should-strip"
        finding = dim["findings"][0]
        del finding["id"]
        finding["parties"] = {"legal": {"note": "x"}, "privacy": {}}
        finding["audit"] = {"trace_id": "should-strip"}
        finding["suggestion"] = {"text": "改成字符串建议"}
        finding["citations"] = ["ev-1"]
        draft["parties"] = {"extra": True}
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        assert result["dimensions"][0]["id"]
        assert "title" not in result["dimensions"][0]
        assert result["dimensions"][0]["findings"][0]["id"]
        assert result["dimensions"][0]["findings"][0]["parties"] == ["legal", "privacy"]
        assert result["dimensions"][0]["findings"][0]["suggestion"] == "改成字符串建议"
        assert result["dimensions"][0]["findings"][0]["citations"][0]["id"] == "ev-1"
        assert "audit" not in result["dimensions"][0]["findings"][0]
        assert "parties" not in result

    def test_finalize_cite_alias(self):
        draft = _minimal_draft(cite_id=None, overall="high")
        finding = draft["dimensions"][0]["findings"][0]
        finding["suggestion"] = "必须整改"
        finding["citation_id"] = "ev-1"
        finding.pop("citations", None)
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        cites = result["dimensions"][0]["findings"][0]["citations"]
        assert cites and cites[0]["id"] == "ev-1"
        assert "citation_id" not in result["dimensions"][0]["findings"][0]

    def test_rejects_bad_cite(self):
        draft = _minimal_draft(cite_id="fake-id")
        _, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "fail"
        assert any("fake-id" in e for e in outcome.errors)

    def test_finalize_no_guess_cite(self):
        draft = _minimal_draft(cite_id=None, overall="medium")
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        finding = result["dimensions"][0]["findings"][0]
        assert outcome.status == "fail"
        assert finding["citations"] == []
        assert any("needs citation id" in error for error in outcome.errors)

    def test_finalize_needs_source(self):
        draft = _minimal_draft()
        _, outcome = finalize_review(draft, evidence_packs=[_pack()])
        assert outcome.status == "fail"
        assert any("source_sections are required" in error for error in outcome.errors)

    def test_high_risk_passes(self):
        draft = _minimal_draft(overall="high")
        draft["dimensions"][0]["findings"][0]["suggestion"] = "必须整改"
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        assert result["review_status"] == "machine_passed"
        assert result["human_review"]["status"] == "not_required"
        assert "必须整改" in result["report"]

    def test_high_risk_needs_suggestion(self):
        draft = _minimal_draft(overall="high")
        draft["dimensions"][0]["findings"][0]["suggestion"] = None
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "fail"
        assert any("requires suggestion" in error for error in outcome.errors)
        assert result["dimensions"][0]["findings"][0]["suggestion"] is None

    def test_empty_retrieval_refusal(self):
        draft = _minimal_draft(cite_id=None, overall="medium")
        draft["dimensions"][0]["findings"][0]["risk"] = "medium"
        errors, _ = validate_review(draft, set(), retrieval_empty=True)
        assert any("needs citation id" in e for e in errors)

    def test_finalize_replace_edit(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["edit"] = {
            "op": "replace",
            "text": "修订后的连续正文。",
        }
        result, outcome = finalize_review(
            draft,
            evidence_packs=[_pack()],
            source_sections=_source(),
        )
        assert outcome.status == "pass"
        edit = result["dimensions"][0]["findings"][0]["edit"]
        assert edit == {"op": "replace", "text": "修订后的连续正文。"}
        assert "建议改文（替换原文）" in result["report"]

    def test_finalize_allows_edit_none(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["edit"] = {"op": "none"}
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        edit = result["dimensions"][0]["findings"][0]["edit"]
        assert edit["op"] == "none"
        assert edit.get("text") is None

    def test_finalize_rejects_empty_edit(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["edit"] = {"op": "replace", "text": ""}
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "fail"
        assert any("edit.text" in e for e in outcome.errors)
        assert result["dimensions"][0]["findings"][0]["edit"] == {"op": "none", "text": None}

    def test_finalize_bad_quote(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["edit"] = {
            "op": "replace",
            "text": "修订后的连续正文。",
        }
        result, outcome = finalize_review(
            draft,
            evidence_packs=[_pack()],
            source_sections=_source("完全不同的原文。"),
        )
        assert outcome.status == "fail"
        assert any("quote not found" in error for error in outcome.errors)
        assert result["dimensions"][0]["findings"][0]["edit"]["op"] == "none"

    def test_finalize_md_quote(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["evidence"]["quote"] = "加密算法：仅支持AES_256、SM4两种选项"
        draft["dimensions"][0]["findings"][0]["edit"] = {
            "op": "replace",
            "text": "加密算法：仅支持 AES_256 一种选项。",
        }
        markdown_body = "**边界规则**\n\n**加密算法：仅支持AES\\_256、SM4两种选项**\n\n**其它**"
        result, outcome = finalize_review(
            draft,
            evidence_packs=[_pack()],
            source_sections=_source(markdown_body),
        )
        assert outcome.status == "pass"
        assert result["dimensions"][0]["findings"][0]["edit"]["op"] == "replace"

    def test_repair_truncated_quote(self):
        full_quote = "§1.5 舆论属性/社会动员能力研判：判定本模块具备舆论属性/社会动员能力，需满足《生成式人工智能服务管理暂行办法》第17条关于安全评估与算法备案的相关要求。"
        body = f"前文。\n\n{full_quote}\n\n后文。"
        truncated = "§1.5 舆论属性/社会动员能力研判：……判定本模块具备舆论属性/社会动员能力……"
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["evidence"]["quote"] = truncated
        draft["dimensions"][0]["findings"][0]["section"] = "§1.5"
        draft["dimensions"][0]["findings"][0]["risk"] = "high"
        draft["dimensions"][0]["findings"][0]["suggestion"] = "补充备案方案"
        pool = [{"section_id": "section-1", "quotes": [full_quote]}]
        result, outcome = finalize_review(
            draft,
            evidence_packs=[_pack()],
            source_sections=_source(body),
            quote_pool=pool,
        )
        assert outcome.status == "pass"
        assert result["dimensions"][0]["findings"][0]["evidence"]["quote"] == full_quote

    def test_repair_ellipsis_quote(self):
        body = "§7.2 宣传/应急部门端交互流程：简报文档首段明确标注以下内容由AI基于公开信息自动生成，用于内部参考，请勿直接对外引用或发布。"
        truncated = "§7.2 宣传/应急部门端交互流程：简报文档首段明确标注以下内容由AI基于公开信息自动生成……"
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["evidence"]["quote"] = truncated
        draft["dimensions"][0]["findings"][0]["section"] = "§7.2"
        draft["dimensions"][0]["findings"][0]["risk"] = "high"
        draft["dimensions"][0]["findings"][0]["suggestion"] = "补充处置流程"
        result, outcome = finalize_review(
            draft,
            evidence_packs=[_pack()],
            source_sections=_source(body),
            quote_pool=[{"section_id": "§7.2", "quotes": [body]}],
        )
        assert outcome.status == "pass"
        assert result["dimensions"][0]["findings"][0]["evidence"]["quote"] == body

    def test_quote_pool_section_lines(self):
        body = "普通段落。\n§4.2 决策类功能属性说明：诉求分类与舆情敏感度分级本质上是决策类功能。\n另一段。"
        quotes = extract_quote_candidates(body)
        assert any("§4.2" in quote for quote in quotes)

    def test_repair_paraphrase(self):
        body = "§3.5 数据跨境传输：所有境外回传数据须先完成脱敏处理并留存审计日志。"
        paraphrase = "数据跨境传输需脱敏并留审计"
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["evidence"]["quote"] = paraphrase
        draft["dimensions"][0]["findings"][0]["section"] = "§3.5"
        draft["dimensions"][0]["findings"][0]["text"] = "缺少跨境合规说明"
        draft["dimensions"][0]["findings"][0]["risk"] = "high"
        draft["dimensions"][0]["findings"][0]["suggestion"] = "补充合规条款"
        result, outcome = finalize_review(
            draft,
            evidence_packs=[_pack()],
            source_sections=_source(body),
            quote_pool=[{"section_id": "§3.5", "quotes": [body]}],
        )
        assert outcome.status == "pass"
        assert body in result["dimensions"][0]["findings"][0]["evidence"]["quote"]

    def test_slim_pool(self):
        pool = [{"section_id": "a", "quotes": ["x" * 300, "short"]}]
        slim = slim_quote_pool(pool, max_quotes=1, max_chars=50)
        assert len(slim[0]["quotes"]) == 1
        assert slim[0]["quotes"][0].endswith("…")

    def test_finalize_rejects_ambiguous_edit(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["edit"] = {
            "op": "replace",
            "text": "修订后的连续正文。",
        }
        result, outcome = finalize_review(
            draft,
            evidence_packs=[_pack()],
            source_sections=_source("原文摘录；原文摘录。"),
        )
        assert outcome.status == "fail"
        assert any("requires a unique" in error for error in outcome.errors)
        assert result["dimensions"][0]["findings"][0]["edit"]["op"] == "none"

    def test_finalize_tool_artifact(self):
        from langchain_core.messages import AIMessage, ToolMessage
        from langgraph.graph import END
        from langgraph.types import Command

        from deerflow.policy_review.tools import finalize_tool

        session = {
            "sections": _source(),
            "packs": [_pack()],
            "retrieval_empty": False,
            "allowed_ids": ["ev-1"],
        }
        runtime = SimpleNamespace(
            state={
                "messages": [
                    ToolMessage(
                        content="{}",
                        tool_call_id="retrieve-1",
                        name="policy_retrieve",
                        artifact=session,
                    )
                ]
            }
        )
        cmd = finalize_tool.func(
            runtime,
            json.dumps(_minimal_draft(), ensure_ascii=False),
            "tc-finalize-1",
        )

        assert isinstance(cmd, Command)
        assert cmd.goto == END
        messages = (cmd.update or {}).get("messages") or []
        assert len(messages) == 2
        assert isinstance(messages[0], ToolMessage)
        assert isinstance(messages[1], AIMessage)
        assert "审查结果已生成" in messages[0].content
        assert messages[0].artifact["review_status"] == "machine_passed"
        assert messages[0].artifact["report"].startswith("# 制度预审报告")
        assert "制度预审报告" in messages[1].content
        assert "schema_hint" not in messages[1].content

    def test_finalize_flat_json(self):
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        from deerflow.policy_review.tools import finalize_tool, parse_draft_in

        flat = {
            "summary": "测试摘要",
            "findings": [
                {
                    "risk": "low",
                    "text": "发现说明",
                    "quote": "原文摘录",
                    "citation_ids": ["ev-1"],
                    "section": "§1",
                }
            ],
        }
        draft_in = parse_draft_in(flat)
        assert draft_in.dimensions[0].findings[0].evidence.quote == "原文摘录"
        assert draft_in.dimensions[0].findings[0].citations[0].id == "ev-1"

        # Models often omit text and stuff prose into parties{role: note}.
        messy = parse_draft_in(
            {
                "summary": "摘要",
                "dimensions": [
                    {
                        "id": "legal",
                        "findings": [
                            {
                                "id": "audit-001",
                                "section": "§1",
                                "risk": "high",
                                "quote": "原文摘录",
                                "parties": {
                                    "legal": "缺少访问控制，存在横向提权风险",
                                    "security": "密钥可被复用",
                                },
                                "suggestion": {"text": "补齐鉴权"},
                                "citation_ids": ["ev-1"],
                            }
                        ],
                    }
                ],
            }
        )
        finding = messy.dimensions[0].findings[0]
        assert "横向提权" in finding.text
        assert finding.parties == ["legal", "security"]
        assert finding.suggestion == "补齐鉴权"

        veto = parse_draft_in(
            {
                "summary": "摘要",
                "findings": [
                    {
                        "risk": "veto",
                        "text": "一票否决项",
                        "quote": "原文摘录",
                        "citation_ids": ["ev-1"],
                        "section": "§1",
                        "suggestion": "整改",
                    }
                ],
            }
        )
        assert veto.dimensions[0].findings[0].risk == "high"

        session = {
            "sections": _source(),
            "packs": [_pack()],
            "retrieval_empty": False,
            "allowed_ids": ["ev-1"],
        }
        runtime = SimpleNamespace(
            state={
                "messages": [
                    ToolMessage(
                        content="{}",
                        tool_call_id="retrieve-1",
                        name="policy_retrieve",
                        artifact=session,
                    )
                ]
            }
        )
        cmd = finalize_tool.func(runtime, json.dumps(flat, ensure_ascii=False), "tc-flat")
        assert isinstance(cmd, Command)
        assert cmd.update["messages"][0].artifact["review_status"] == "machine_passed"

    def test_finalize_tool_retry(self):
        from langchain_core.messages import AIMessage, ToolMessage
        from langgraph.graph import END
        from langgraph.types import Command

        from deerflow.policy_review.tools import MAX_FINALIZE_ATTEMPTS, finalize_tool

        session = {
            "sections": _source(),
            "packs": [_pack()],
            "retrieval_empty": False,
            "allowed_ids": ["ev-1"],
        }
        retrieve = ToolMessage(
            content="{}",
            tool_call_id="retrieve-1",
            name="policy_retrieve",
            artifact=session,
        )
        bad = json.dumps(_minimal_draft(cite_id="fake-id"), ensure_ascii=False)
        runtime = SimpleNamespace(state={"messages": [retrieve]})

        cmd1 = finalize_tool.func(runtime, bad, "tc-fail-1")
        assert isinstance(cmd1, Command)
        assert cmd1.goto is None or cmd1.goto != END
        msgs1 = (cmd1.update or {}).get("messages") or []
        assert len(msgs1) == 1
        assert isinstance(msgs1[0], ToolMessage)
        payload1 = json.loads(msgs1[0].content)
        assert payload1["ok"] is False
        assert payload1["retry"] is True
        assert payload1["attempt"] == 1
        assert payload1["allowed_refs"] == ["ev-1"]
        assert "result" not in payload1

        prior = [ToolMessage(content="{}", tool_call_id=f"prev-{i}", name="policy_finalize") for i in range(MAX_FINALIZE_ATTEMPTS - 1)]
        runtime.state = {"messages": [retrieve, *prior]}
        cmd_last = finalize_tool.func(runtime, bad, "tc-fail-last")
        assert isinstance(cmd_last, Command)
        assert cmd_last.goto == END
        msgs_last = (cmd_last.update or {}).get("messages") or []
        assert isinstance(msgs_last[0], ToolMessage)
        assert isinstance(msgs_last[1], AIMessage)
        assert "审查未通过机器校验" in msgs_last[0].content
        assert msgs_last[0].artifact["review_status"] == "machine_failed"
        assert "制度预审报告" in msgs_last[1].content

    def test_finalize_tool_junk(self):
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        from deerflow.policy_review.tools import finalize_tool

        session = {
            "sections": _source(),
            "packs": [_pack()],
            "retrieval_empty": False,
            "allowed_ids": ["ev-1"],
        }
        runtime = SimpleNamespace(
            state={
                "messages": [
                    ToolMessage(
                        content="{}",
                        tool_call_id="retrieve-1",
                        name="policy_retrieve",
                        artifact=session,
                    )
                ]
            }
        )
        dirty = json.dumps(_minimal_draft(), ensure_ascii=False) + "\n说明：以上为草稿"
        cmd = finalize_tool.func(runtime, dirty, "tc-junk")
        assert isinstance(cmd, Command)
        assert "制度预审报告" in cmd.update["messages"][1].content
        assert cmd.update["messages"][0].artifact["review_status"] == "machine_passed"

        # Direct .func still accepts object for harness salvage / unit tests.
        cmd2 = finalize_tool.func(runtime, _minimal_draft(), "tc-obj")
        assert isinstance(cmd2, Command)
        assert cmd2.update["messages"][0].artifact["review_status"] == "machine_passed"

        fenced = f"```json\n{json.dumps(_minimal_draft(), ensure_ascii=False)}\n```"
        cmd3 = finalize_tool.func(runtime, fenced, "tc-fenced")
        assert isinstance(cmd3, Command)
        assert cmd3.update["messages"][0].artifact["review_status"] == "machine_passed"

        prefixed = "draft follows:\n" + json.dumps(_minimal_draft(), ensure_ascii=False)
        cmd4 = finalize_tool.func(runtime, prefixed, "tc-prefix")
        assert isinstance(cmd4, Command)
        assert cmd4.update["messages"][0].artifact["review_status"] == "machine_passed"

    def test_finalize_tool_parse_err(self):
        from langchain_core.messages import ToolMessage
        from langgraph.graph import END
        from langgraph.types import Command

        from deerflow.policy_review.tools import finalize_tool

        session = {
            "sections": _source(),
            "packs": [_pack()],
            "retrieval_empty": False,
            "allowed_ids": ["ev-1"],
        }
        runtime = SimpleNamespace(
            state={
                "messages": [
                    ToolMessage(
                        content="{}",
                        tool_call_id="retrieve-1",
                        name="policy_retrieve",
                        artifact=session,
                    )
                ]
            }
        )
        cmd = finalize_tool.func(runtime, "{not-json", "tc-parse-1")
        assert isinstance(cmd, Command)
        assert cmd.goto == END
        assert "制度预审报告" in cmd.update["messages"][1].content
        assert "审查未通过机器校验" in cmd.update["messages"][0].content
        assert cmd.update["messages"][0].artifact["review_status"] == "machine_failed"

    @pytest.mark.asyncio
    async def test_prepare_tool_upload(self, tmp_path, monkeypatch):
        from langgraph.types import Command

        from deerflow.config import paths as paths_mod
        from deerflow.config.paths import Paths
        from deerflow.policy_review.tools import prepare_tool
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        class _U:
            id = "u-test"

        token = set_current_user(_U())
        monkeypatch.setattr(paths_mod, "_paths", Paths(tmp_path))
        thread_id = "thread-prep-1"
        uploads = tmp_path / "users" / "u-test" / "threads" / thread_id / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        doc = uploads / "sample.md"
        doc.write_text("# 标题\n\n这是一段用于预审的正文。\n", encoding="utf-8")

        def _fake_prepare(path, title=None):
            assert Path(path) == doc.resolve()
            return {
                "source_path": str(path),
                "title": title or "sample",
                "parse_quality": "ok",
                "sections": [{"title": "标题", "level": 1, "body": "这是一段用于预审的正文。"}],
                "section_count": 1,
            }

        async def _fake_retrieve(runtime, sections_json, spaces, top_k):
            sections = json.loads(sections_json)["sections"]
            return (
                {
                    "allowed_ids": ["ev-1"],
                    "retrieval_empty": False,
                    "section_results": [],
                    "quote_pool": [{"section_id": "标题", "quotes": ["这是一段用于预审的正文。"]}],
                    "draft_scaffold": {"summary": ""},
                    "scenario": "policy-review",
                    "packs": [],
                },
                {
                    "sections": sections,
                    "packs": [],
                    "retrieval_empty": False,
                    "allowed_ids": ["ev-1"],
                    "scaffold": {"summary": ""},
                    "quote_pool": [],
                    "spaces_queried": [],
                },
            )

        try:
            runtime = SimpleNamespace(
                context={"user_id": "u-test", "thread_id": thread_id},
                state={
                    "thread_data": {
                        "workspace_path": str(uploads.parent / "workspace"),
                        "uploads_path": str(uploads),
                        "outputs_path": str(uploads.parent / "outputs"),
                    }
                },
            )
            with (
                patch(
                    "deerflow.policy_review.tools.prepare_sections",
                    side_effect=_fake_prepare,
                ),
                patch(
                    "deerflow.policy_review.tools.retrieve_async",
                    side_effect=_fake_retrieve,
                ),
            ):
                cmd = await prepare_tool.coroutine(
                    runtime,
                    "tc-prep-1",
                    "/mnt/user-data/uploads/sample.md",
                )
            assert isinstance(cmd, Command)
            msg = cmd.update["messages"][0]
            payload = json.loads(msg.content)
            assert payload["prepare"]["section_count"] == 1
            assert payload["allowed_ids"] == ["ev-1"]
            assert msg.artifact["allowed_ids"] == ["ev-1"]
        finally:
            reset_current_user(token)
            monkeypatch.setattr(paths_mod, "_paths", None)

    @pytest.mark.asyncio
    async def test_prepare_default_upload(self, tmp_path, monkeypatch):
        from langgraph.types import Command

        from deerflow.config import paths as paths_mod
        from deerflow.config.paths import Paths
        from deerflow.policy_review.tools import prepare_tool
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        class _U:
            id = "u-test"

        token = set_current_user(_U())
        monkeypatch.setattr(paths_mod, "_paths", Paths(tmp_path))
        thread_id = "thread-prep-auto"
        uploads = tmp_path / "users" / "u-test" / "threads" / thread_id / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        doc = uploads / "auto.docx"
        doc.write_bytes(b"PK fake docx")

        def _fake_prepare(path, title=None):
            assert Path(path) == doc.resolve()
            return {
                "source_path": str(path),
                "title": "auto",
                "parse_quality": "ok",
                "sections": [{"title": "s", "level": 1, "body": "body"}],
                "section_count": 1,
            }

        async def _fake_retrieve(runtime, sections_json, spaces, top_k):
            return (
                {
                    "allowed_ids": [],
                    "retrieval_empty": True,
                    "section_results": [],
                    "quote_pool": [],
                    "draft_scaffold": {"summary": ""},
                    "scenario": "policy-review",
                    "packs": [],
                },
                {
                    "sections": [{"title": "s", "level": 1, "body": "body"}],
                    "packs": [],
                    "retrieval_empty": True,
                    "allowed_ids": [],
                    "scaffold": {"summary": ""},
                    "quote_pool": [],
                    "spaces_queried": [],
                },
            )

        try:
            runtime = SimpleNamespace(
                context={"user_id": "u-test", "thread_id": thread_id},
                state={
                    "thread_data": {
                        "workspace_path": str(uploads.parent / "workspace"),
                        "uploads_path": str(uploads),
                        "outputs_path": str(uploads.parent / "outputs"),
                    },
                    "uploaded_files": [
                        {
                            "filename": "auto.docx",
                            "size": 12,
                            "path": "/mnt/user-data/uploads/auto.docx",
                        }
                    ],
                },
            )
            with (
                patch(
                    "deerflow.policy_review.tools.prepare_sections",
                    side_effect=_fake_prepare,
                ),
                patch(
                    "deerflow.policy_review.tools.retrieve_async",
                    side_effect=_fake_retrieve,
                ),
            ):
                cmd = await prepare_tool.coroutine(runtime, "tc-prep-auto", None)
            assert isinstance(cmd, Command)
            payload = json.loads(cmd.update["messages"][0].content)
            assert payload["prepare"]["section_count"] == 1
            assert payload["retrieval_empty"] is True
        finally:
            reset_current_user(token)
            monkeypatch.setattr(paths_mod, "_paths", None)

    @pytest.mark.asyncio
    async def test_prepare_rejects_path(self, tmp_path, monkeypatch):
        from deerflow.config import paths as paths_mod
        from deerflow.config.paths import Paths
        from deerflow.policy_review.tools import prepare_tool
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        class _U:
            id = "u-test"

        token = set_current_user(_U())
        monkeypatch.setattr(paths_mod, "_paths", Paths(tmp_path))
        thread_id = "t1"
        (tmp_path / "users" / "u-test" / "threads" / thread_id / "user-data" / "uploads").mkdir(parents=True)
        try:
            root = tmp_path / "users" / "u-test" / "threads" / thread_id / "user-data"
            runtime = SimpleNamespace(
                context={"user_id": "u-test", "thread_id": thread_id},
                state={
                    "thread_data": {
                        "workspace_path": str(root / "workspace"),
                        "uploads_path": str(root / "uploads"),
                        "outputs_path": str(root / "outputs"),
                    }
                },
            )
            # Host absolute path is not a /mnt/user-data virtual path → sandbox helper rejects.
            raw = await prepare_tool.coroutine(runtime, "tc-bad", "/etc/passwd")
            payload = json.loads(raw)
            assert "error" in payload
        finally:
            reset_current_user(token)
            monkeypatch.setattr(paths_mod, "_paths", None)

    def test_rejects_dup_ids(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"].append(
            {
                "id": "f1",
                "section": "§2",
                "risk": "low",
                "confidence": "high",
                "text": "重复 id",
                "evidence": {"quote": "原文摘录"},
                "citations": [{"id": "ev-1"}],
            }
        )
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        # Server dedupes colliding finding ids instead of failing the whole review.
        assert outcome.status == "pass"
        ids = [f["id"] for f in result["dimensions"][0]["findings"]]
        assert len(ids) == len(set(ids))

    def test_rejects_unknown_fields(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["mystery"] = "nope"
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        # Unknown finding keys are stripped server-side (closed contract).
        assert outcome.status == "pass"
        assert "mystery" not in result["dimensions"][0]["findings"][0]

    @pytest.mark.asyncio
    async def test_retrieve_parallel(self):
        from deerflow.config.knowledge_config import (
            KnowledgeConfig,
            KnowledgeScenarioConfig,
            get_knowledge_config,
            set_knowledge_config,
        )

        prev = get_knowledge_config()
        set_knowledge_config(
            KnowledgeConfig(
                scenarios=[
                    KnowledgeScenarioConfig(
                        type="policy-review",
                        top_k=10,
                        score=0.3,
                        fusion_num_queries=1,
                        merge_mode="slot_then_rrf",
                    )
                ]
            )
        )
        space_hits = {
            "legal": [
                {
                    "id": "law-1",
                    "source": "legal",
                    "kind": "policy",
                    "title": "law",
                    "snippet": "s",
                    "score": 0.9,
                    "metadata": {"space_id": "legal"},
                }
            ],
            "company": [
                {
                    "id": "co-1",
                    "source": "legal",
                    "kind": "policy",
                    "title": "co",
                    "snippet": "s",
                    "score": 0.85,
                    "metadata": {"space_id": "company"},
                }
            ],
            "reference": [
                {
                    "id": "ref-1",
                    "source": "legal",
                    "kind": "reference",
                    "title": "ref",
                    "snippet": "s",
                    "score": 0.8,
                    "metadata": {"space_id": "reference"},
                }
            ],
            "case": [
                {
                    "id": "case-1",
                    "source": "legal",
                    "kind": "case",
                    "title": "case",
                    "snippet": "s",
                    "score": 0.95,
                    "metadata": {"space_id": "case"},
                }
            ],
        }

        def _fake_search_one(*, space_id, **kwargs):
            return list(space_hits.get(space_id, []))

        try:
            with (
                patch(
                    "deerflow.knowledge.app.query.list_accessible_spaces",
                    new=AsyncMock(return_value=[SimpleNamespace(id=sid, default_scenarios=["policy-review"]) for sid in ("legal", "company", "reference", "case")]),
                ),
                patch("deerflow.knowledge.app.query.retrieve_in_space", side_effect=_fake_search_one),
            ):
                out = await retrieve_for_sections(
                    session=object(),
                    user_id="u1",
                    system_role="user",
                    sections=[{"id": "s1", "title": "s1", "body": "甲方应按约定及时付款并开具发票。"}],
                    spaces=["legal", "company", "reference", "case"],
                    scenario="policy-review",
                    top_k=4,
                )
        finally:
            set_knowledge_config(prev)

        assert set(out["allowed_ids"]) == {"law-1", "co-1", "ref-1", "case-1"}
        assert set(item["id"] for item in out["packs"][0]["items"]) == {
            "law-1",
            "co-1",
            "ref-1",
            "case-1",
        }
        assert len(out["section_results"][0]["space_results"]) == 4
        assert out["quote_pool"][0]["quotes"]
        assert out["draft_scaffold"]["schema_hint"] == "legal-review.v1"
        assert out["draft_scaffold"]["dimensions"][0]["id"] == "s1"
        digest_ids = {ev["id"] for ev in out["evidence_digest"][0]["evidence"]}
        assert digest_ids == {"law-1", "co-1", "ref-1", "case-1"}
        assert all("snippet" in ev for ev in out["evidence_digest"][0]["evidence"])

    def test_merge_sections_cap(self):
        sections = [{"id": f"section-{index}", "title": f"§{index}", "body": f"正文{index}。"} for index in range(1, 25)]
        merged = merge_sections(sections)
        assert len(merged) == 16
        assert all(section["id"].startswith("section-") for section in merged)

    def test_digest_snippets(self):
        section_results = [{"section_id": "s1", "hit_count": 2}]
        packs = [
            {
                "items": [
                    {
                        "id": "law-1",
                        "kind": "regulation",
                        "source": "legal",
                        "citable_as": "PIPL / 第1条",
                        "snippet": "个人信息处理应当具有明确、合理的目的。",
                    },
                    {
                        "id": "co-1",
                        "kind": "policy",
                        "source": "company",
                        "citable_as": "内规-1",
                        "snippet": "数据出境须评估。",
                    },
                ]
            }
        ]
        digest = build_evidence_digest(section_results, packs)
        assert digest[0]["section_id"] == "s1"
        assert digest[0]["evidence"][0]["snippet"]
        assert digest[0]["evidence"][0]["citable_as"] == "PIPL / 第1条"

    def test_quote_pool_stable(self):
        sections = [
            {
                "id": "section-1",
                "title": "第一条",
                "body": "甲方应按约定付款。乙方应及时交付货物。双方应保守商业秘密。",
            }
        ]
        a = extract_quote_candidates(sections[0]["body"])
        b = extract_quote_candidates(sections[0]["body"])
        assert a == b
        assert a
        scaffold = build_draft_scaffold(sections, allowed_ids=["ev-1"], retrieval_empty=False)
        assert scaffold["dimensions"][0]["id"] == "section-1"
        assert scaffold["audit"]["allowed_refs"] == ["ev-1"]
        assert "refusal" not in scaffold
        empty = build_draft_scaffold(sections, allowed_ids=[], retrieval_empty=True)
        assert empty["refusal"]["reason"] == "empty_retrieval"

    @pytest.mark.asyncio
    async def test_retrieve_tool_scope(self):
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        from deerflow.knowledge.runtime import (
            reset_agent_knowledge_defaults,
            set_agent_knowledge_defaults,
        )
        from deerflow.policy_review.tools import retrieve_tool

        token = set_agent_knowledge_defaults(spaces=["bound-space"], scenario=None)
        captured: dict = {}

        async def _fake_retrieve(**kwargs):
            captured.update(kwargs)
            return {
                "packs": [],
                "allowed_ids": [],
                "retrieval_empty": True,
                "section_results": [],
                "scenario": "policy-review",
            }

        try:
            with (
                patch("deerflow.config.knowledge_config.get_knowledge_config") as gk,
                patch("deerflow.knowledge.runtime.knowledge_extra_available", return_value=True),
                patch("deerflow.runtime.user_context.get_current_user") as gu,
                patch("deerflow.persistence.engine.get_session_factory") as sf,
                patch(
                    "deerflow.policy_review.tools.retrieve_for_sections",
                    new=AsyncMock(side_effect=_fake_retrieve),
                ),
            ):
                gk.return_value.enabled = True
                gu.return_value = type("U", (), {"id": "u1", "system_role": "user"})()
                factory = MagicMock()
                sf.return_value = factory
                runtime = SimpleNamespace(
                    context={"user_id": "u1", "thread_id": "t1"},
                    state={},
                )
                cmd = await retrieve_tool.coroutine(
                    runtime,
                    '[{"title":"s","body":"b"}]',
                    "retrieve-1",
                    None,
                )
        finally:
            reset_agent_knowledge_defaults(token)

        assert captured.get("spaces") is None
        assert isinstance(cmd, Command)
        message = cmd.update["messages"][0]
        assert isinstance(message, ToolMessage)
        result = json.loads(message.content)
        session = message.artifact
        assert result["retrieval_empty"] is True
        assert "packs" not in result
        assert session is not None
        assert session["packs"] == []
        assert session["sections"][0]["title"] == "s"

    @pytest.mark.asyncio
    async def test_retrieve_restore_sections(self):
        """Body-less section_results reuse prior prepare sections for quote_pool."""
        from langchain_core.messages import ToolMessage

        from deerflow.policy_review.tools import retrieve_async

        prior_sections = [
            {
                "id": "section-1",
                "title": "第一条",
                "body": "甲方应按约定付款并及时开具发票。",
            }
        ]
        prior_session = {
            "sections": prior_sections,
            "packs": [],
            "retrieval_empty": True,
            "allowed_ids": [],
            "scaffold": {"schema_hint": "legal-review.v1"},
            "quote_pool": [{"section_id": "section-1", "quotes": ["甲方应按约定付款并及时开具发票。"]}],
        }
        runtime = SimpleNamespace(
            context={"user_id": "u1", "thread_id": "t1"},
            state={
                "messages": [
                    ToolMessage(
                        content="{}",
                        tool_call_id="prepare-1",
                        name="policy_prepare",
                        artifact=prior_session,
                    )
                ]
            },
        )
        captured: dict = {}

        async def _fake_retrieve(**kwargs):
            captured.update(kwargs)
            return {
                "packs": [],
                "allowed_ids": [],
                "retrieval_empty": True,
                "section_results": [
                    {
                        "section_id": "section-1",
                        "query": "第一条",
                        "hit_count": 0,
                        "space_results": [],
                    }
                ],
                "quote_pool": [{"section_id": "section-1", "quotes": ["甲方应按约定付款并及时开具发票。"]}],
                "draft_scaffold": {"schema_hint": "legal-review.v1"},
                "scenario": "policy-review",
            }

        with (
            patch("deerflow.config.knowledge_config.get_knowledge_config") as gk,
            patch("deerflow.knowledge.runtime.knowledge_extra_available", return_value=True),
            patch("deerflow.runtime.user_context.get_current_user") as gu,
            patch("deerflow.persistence.engine.get_session_factory") as sf,
            patch(
                "deerflow.policy_review.tools.retrieve_for_sections",
                new=AsyncMock(side_effect=_fake_retrieve),
            ),
        ):
            gk.return_value.enabled = True
            gu.return_value = type("U", (), {"id": "u1", "system_role": "user"})()
            sf.return_value = MagicMock()
            result, session = await retrieve_async(
                runtime,
                json.dumps(
                    {
                        "section_results": [
                            {
                                "section_id": "section-1",
                                "query": "第一条\n甲方应按约定付款并及时开具发票。",
                                "hit_count": 0,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                spaces=None,
                top_k=None,
            )

        assert captured == {}
        assert result.get("cached") is True
        assert session is prior_session
        assert result["quote_pool"][0]["quotes"]

    @pytest.mark.asyncio
    async def test_retrieve_restore_body(self):
        """Body-less section_results reuse prior prepare sections when re-searching."""
        from langchain_core.messages import ToolMessage

        from deerflow.policy_review.tools import retrieve_async

        prior_sections = [
            {
                "id": "section-1",
                "title": "第一条",
                "body": "甲方应按约定付款并及时开具发票。",
            },
            {
                "id": "section-2",
                "title": "第二条",
                "body": "乙方应按时交付。",
            },
        ]
        prior_session = {
            "sections": prior_sections[:1],
            "packs": [{"items": []}],
            "retrieval_empty": True,
            "allowed_ids": [],
            "scaffold": {"schema_hint": "legal-review.v1"},
            "quote_pool": [],
        }
        runtime = SimpleNamespace(
            context={"user_id": "u1", "thread_id": "t1"},
            state={
                "messages": [
                    ToolMessage(
                        content="{}",
                        tool_call_id="prepare-1",
                        name="policy_prepare",
                        artifact=prior_session,
                    )
                ]
            },
        )
        captured: dict = {}

        async def _fake_retrieve(**kwargs):
            captured.update(kwargs)
            return {
                "packs": [{"items": []}, {"items": []}],
                "allowed_ids": [],
                "retrieval_empty": True,
                "section_results": [],
                "quote_pool": [],
                "draft_scaffold": {"schema_hint": "legal-review.v1"},
                "scenario": "policy-review",
                "evidence_digest": [],
            }

        with (
            patch("deerflow.config.knowledge_config.get_knowledge_config") as gk,
            patch("deerflow.knowledge.runtime.knowledge_extra_available", return_value=True),
            patch("deerflow.runtime.user_context.get_current_user") as gu,
            patch("deerflow.persistence.engine.get_session_factory") as sf,
            patch(
                "deerflow.policy_review.tools.retrieve_for_sections",
                new=AsyncMock(side_effect=_fake_retrieve),
            ),
        ):
            gk.return_value.enabled = True
            gu.return_value = type("U", (), {"id": "u1", "system_role": "user"})()
            sf.return_value = MagicMock()
            await retrieve_async(
                runtime,
                json.dumps({"sections": prior_sections}, ensure_ascii=False),
                spaces=None,
                top_k=None,
            )

        assert captured["sections"] == prior_sections
        assert captured["sections"][1]["body"]

    def test_finalize_gate_pool(self):
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        from deerflow.policy_review.tools import finalize_gate, retry_to_model

        pool = [{"section_id": "§1", "quotes": ["原文摘录"]}]
        cmd = retry_to_model(
            tool_call_id="tc-retry",
            attempt=1,
            errors=["evidence.quote must match quote_pool"],
            allowed_refs=["ev-1"],
            quote_pool=pool,
        )
        assert isinstance(cmd, Command)
        envelope = json.loads(cmd.update["messages"][0].content)
        assert envelope["quote_pool"] == pool

        session = {
            "sections": _source(),
            "packs": [_pack()],
            "retrieval_empty": False,
            "allowed_ids": ["ev-1"],
            "quote_pool": pool,
            "scaffold": {"schema_hint": "legal-review.v1"},
        }
        runtime = SimpleNamespace(
            state={
                "messages": [
                    ToolMessage(
                        content="{}",
                        tool_call_id="retrieve-1",
                        name="policy_retrieve",
                        artifact=session,
                    )
                ]
            }
        )
        gated = finalize_gate(
            runtime=runtime,
            tool_call_id="tc-gate",
            result={"audit": {"allowed_refs": ["ev-1"]}},
            ok=False,
            errors=["Finding f1 evidence.quote is not in quote_pool"],
        )
        assert isinstance(gated, Command)
        gated_payload = json.loads(gated.update["messages"][0].content)
        assert gated_payload["retry"] is True
        assert gated_payload["quote_pool"] == pool


class TestPolicyFlow:
    """Once prepare/retrieve starts, force finalize; prose is a last-resort nudge."""

    def test_idle_before_policy(self):
        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from langchain_core.messages import AIMessage, HumanMessage

        from deerflow.policy_review.flow import PolicyFlowMiddleware, bind_next_step

        mw = PolicyFlowMiddleware()
        state = {
            "uploaded_files": [{"filename": "prd.docx", "path": "/mnt/user-data/uploads/prd.docx"}],
            "messages": [
                HumanMessage(content="预审这份文件"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "ask_clarification",
                            "args": {
                                "question": "How should I read the docx?",
                                "clarification_type": "approach_choice",
                            },
                        }
                    ],
                ),
            ],
        }
        # Agent still owns tool choice before a policy tool starts.
        assert mw.after_model(state, runtime=SimpleNamespace()) is None
        tools = [
            SimpleNamespace(name="ask_clarification"),
            SimpleNamespace(name="policy_prepare"),
            SimpleNamespace(name="policy_finalize"),
        ]
        request = ModelRequest(
            model=FakeListChatModel(responses=["ok"]),
            messages=state["messages"],
            tools=tools,
            tool_choice=None,
            state=state,
            runtime=SimpleNamespace(),
            model_settings={},
        )
        assert bind_next_step(request) is request

    def test_force_finalize(self):
        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from langchain_core.messages import HumanMessage, ToolMessage

        from deerflow.policy_review.flow import bind_next_step, next_step

        messages = [
            HumanMessage(content="预审这份文件"),
            ToolMessage(
                content="{}",
                tool_call_id="p1",
                name="policy_prepare",
                artifact={"scaffold": {"summary": ""}, "packs": [], "allowed_ids": []},
            ),
        ]
        assert next_step(messages) == "policy_finalize"
        tools = [
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="policy_retrieve"),
            SimpleNamespace(name="policy_finalize"),
            SimpleNamespace(name="policy_prepare"),
        ]
        request = ModelRequest(
            model=FakeListChatModel(responses=["ok"]),
            messages=messages,
            tools=tools,
            tool_choice=None,
            state={"messages": messages},
            runtime=SimpleNamespace(),
            model_settings={},
        )
        bound = bind_next_step(request)
        assert bound is not request
        assert [t.name for t in bound.tools] == ["policy_finalize"]
        assert bound.tool_choice == "policy_finalize"
        assert bound.model_settings.get("parallel_tool_calls") is False

    def test_after_model_tool_calls(self):
        """after_model does not clear in-flight tool calls; wrap_model_call gates tools."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import PolicyFlowMiddleware

        mw = PolicyFlowMiddleware()
        state = {
            "messages": [
                HumanMessage(content="预审"),
                ToolMessage(
                    content="{}",
                    tool_call_id="p1",
                    name="policy_prepare",
                    artifact={"scaffold": {"summary": ""}, "packs": [], "allowed_ids": []},
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "f1",
                            "name": "policy_finalize",
                            "args": {"draft": {"summary": "s", "dimensions": []}},
                        }
                    ],
                ),
            ],
        }
        assert mw.after_model(state, runtime=SimpleNamespace()) is None

    def test_nudge_to_finalize(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import PolicyFlowMiddleware, next_step

        mw = PolicyFlowMiddleware()
        state = {
            "messages": [
                HumanMessage(content="预审这份文件"),
                ToolMessage(
                    content="{}",
                    tool_call_id="p1",
                    name="policy_prepare",
                    artifact={"scaffold": {"summary": ""}, "packs": [], "allowed_ids": []},
                ),
                AIMessage(content="分析问题…", tool_calls=[]),
            ]
        }
        assert next_step(state["messages"]) == "policy_finalize"
        out = mw.after_model(state, runtime=SimpleNamespace())
        assert out is not None
        assert out["jump_to"] == "model"
        assert "policy_finalize" in out["messages"][1].content

    def test_nudge_after_prose(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import (
            REMINDER_NAME,
            PolicyFlowMiddleware,
            next_step,
        )

        mw = PolicyFlowMiddleware()
        state = {
            "messages": [
                HumanMessage(content="预审这份文件"),
                ToolMessage(content="{}", tool_call_id="r1", name="policy_retrieve"),
                AIMessage(content="分析问题：检索已成功，但 finalize 失败…", tool_calls=[]),
            ]
        }
        out = mw.after_model(state, runtime=SimpleNamespace())
        assert out is not None
        assert out["jump_to"] == "model"
        assert next_step(state["messages"]) == "policy_finalize"
        cleared, reminder = out["messages"]
        assert isinstance(cleared, AIMessage)
        assert cleared.content == ""
        assert isinstance(reminder, HumanMessage)
        assert reminder.name == REMINDER_NAME
        assert "policy_finalize" in reminder.content

    def test_salvage_finalize(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import PolicyFlowMiddleware

        draft = {
            "summary": "测试摘要",
            "findings": [
                {
                    "risk": "low",
                    "text": "发现说明",
                    "quote": "原文摘录",
                    "citation_ids": ["ev-1"],
                    "section": "§1",
                }
            ],
        }
        session = {
            "sections": _source(),
            "packs": [_pack()],
            "retrieval_empty": False,
            "allowed_ids": ["ev-1"],
            "scaffold": {"summary": "", "dimensions": []},
            "quote_pool": [{"section_id": "§1", "quotes": ["原文摘录"]}],
        }
        mw = PolicyFlowMiddleware()
        state = {
            "messages": [
                HumanMessage(content="预审"),
                ToolMessage(
                    content="{}",
                    tool_call_id="p1",
                    name="policy_prepare",
                    artifact=session,
                ),
                AIMessage(
                    content="",
                    tool_calls=[],
                    invalid_tool_calls=[
                        {
                            "id": "bad-1",
                            "name": "policy_finalize",
                            "args": "{}",
                            "error": "Invalid args",
                        }
                    ],
                    additional_kwargs={
                        "tool_calls": [
                            {
                                "id": "bad-1",
                                "type": "function",
                                "function": {
                                    "name": "policy_finalize",
                                    "arguments": json.dumps(
                                        {"draft": json.dumps(draft, ensure_ascii=False)},
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        ]
                    },
                ),
            ]
        }
        out = mw.after_model(state, runtime=SimpleNamespace())
        assert out is not None
        assert out["jump_to"] == "end"
        assert any(isinstance(msg, ToolMessage) and msg.name == "policy_finalize" for msg in out["messages"])
        tool_msg = next(msg for msg in out["messages"] if isinstance(msg, ToolMessage))
        assert tool_msg.artifact["review_status"] == "machine_passed"
        assert len(findings_of := __import__("deerflow.policy_review.render", fromlist=["findings_of"]).findings_of(tool_msg.artifact)) == 1
        assert findings_of[0]["text"] == "发现说明"

    def test_hard_abort_at_cap(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import (
            MAX_REMINDERS,
            REMINDER_NAME,
            PolicyFlowMiddleware,
        )

        mw = PolicyFlowMiddleware()
        reminders = [HumanMessage(name=REMINDER_NAME, content="<system_reminder>x</system_reminder>") for _ in range(MAX_REMINDERS)]
        state = {
            "messages": [
                HumanMessage(content="预审这份文件"),
                ToolMessage(content="{}", tool_call_id="r1", name="policy_retrieve"),
                *reminders,
                AIMessage(content="还是分析一下…", tool_calls=[]),
            ]
        }
        out = mw.after_model(state, runtime=SimpleNamespace())
        assert out is not None
        assert out["jump_to"] == "end"
        assert "制度预审报告" in out["messages"][0].content
        assert "机器预审未通过" in out["messages"][0].content

    def test_exit_after_deliver(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import PolicyFlowMiddleware

        mw = PolicyFlowMiddleware()
        # Server-rendered report keeps as-is.
        state = {
            "messages": [
                HumanMessage(content="预审"),
                ToolMessage(content="{}", tool_call_id="r1", name="policy_retrieve"),
                ToolMessage(
                    content=json.dumps({"ok": True, "retry": False, "result": {"schema_hint": "legal-review.v1"}}),
                    tool_call_id="f1",
                    name="policy_finalize",
                ),
                AIMessage(
                    content="# 制度预审报告\n\n通过",
                    id="structured-deliver:legal-review:f1",
                    tool_calls=[],
                ),
            ]
        }
        assert mw.after_model(state, runtime=SimpleNamespace()) is None

        # Extra model prose after success is cleared (not shown as "errors").
        state["messages"][-1] = AIMessage(
            content="Schema 违规：早期 draft 缺失…",
            tool_calls=[],
        )
        out = mw.after_model(state, runtime=SimpleNamespace())
        assert out is not None
        assert out["jump_to"] == "end"
        assert out["messages"][0].content == ""

    def test_exit_cn_deliver(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import PolicyFlowMiddleware, finalize_delivered

        messages = [
            HumanMessage(content="预审"),
            ToolMessage(content="{}", tool_call_id="r1", name="policy_retrieve"),
            ToolMessage(
                content="审查结果已生成：请查看上方 Markdown 报告；结构化 JSON 见本工具输出。",
                tool_call_id="f1",
                name="policy_finalize",
                artifact={
                    "schema_hint": "legal-review.v1",
                    "review_status": "machine_passed",
                },
            ),
            AIMessage(
                content="# 制度预审报告\n\n通过",
                id="structured-deliver:legal-review:f1",
                tool_calls=[],
            ),
        ]
        assert finalize_delivered(messages) is True
        mw = PolicyFlowMiddleware()
        assert mw.after_model({"messages": messages}, runtime=SimpleNamespace()) is None

    def test_reject_model_result(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from deerflow.policy_review.flow import PolicyFlowMiddleware

        mw = PolicyFlowMiddleware()
        state = {
            "messages": [
                HumanMessage(content="预审"),
                ToolMessage(content="{}", tool_call_id="r1", name="policy_retrieve"),
                AIMessage(content='{"schema_hint":"legal-review.v1"}'),
            ]
        }
        out = mw.after_model(state, runtime=SimpleNamespace())
        assert out is not None
        assert out["jump_to"] == "model"
