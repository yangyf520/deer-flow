"""Tests for deerflow.policy_review (legal-review.v1)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.policy_review.pipeline import (
    build_draft_scaffold,
    build_evidence_digest,
    empty_section_pack,
    extract_quote_candidates,
    finalize_review,
    merge_sections,
    retrieve_for_sections,
    section_query,
)
from deerflow.policy_review.validate import validate_review


def test_section_query_accepts_section_results_shape():
    """Model may re-feed section_results (section_id + query) into retrieve."""
    assert section_query({"section_id": "section-1", "query": "密钥管理\n范围"}) == "密钥管理\n范围"
    assert section_query({"id": "s1", "title": "范围", "body": "正文"}) == "范围\n正文"
    assert section_query({}) == ""


@pytest.mark.asyncio
async def test_retrieve_skips_empty_query_without_calling_search():
    search = AsyncMock()
    with patch("deerflow.knowledge.service.search", search):
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

    def test_finalize_passes_with_grounded_citations(self):
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

    def test_spaces_from_packs_dedupes_in_order(self):
        from deerflow.policy_review.pipeline import spaces_from_packs

        packs = [
            {"items": [{"id": "a", "metadata": {"space_id": "legal"}}]},
            {"items": [{"id": "b", "metadata": {"space_id": "legal"}}, {"id": "c", "metadata": {"space_id": "hr"}}]},
            {"items": [{"id": "d", "metadata": {}}]},
        ]
        assert spaces_from_packs(packs) == ["legal", "hr"]

    def test_humanize_error_maps_schema_and_flow_noise(self):
        from deerflow.policy_review.render import humanize_error

        assert "发现项缺少完整说明" in humanize_error("$.dimensions[0].findings[0].text: Field required")
        assert "预审流程未完成" in humanize_error("Policy review incomplete: model exited before policy_finalize")
        # Bare JSONPath / English schema noise → generic business label
        assert humanize_error("$.audit.pipeline_stages: value is not a valid list") == ("预审结果未通过机器校验，请按报告说明处理后重新预审。")

    def test_report_sanitizes_snippet_noise_and_uses_tables(self):
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

    def test_report_orders_findings_by_risk_and_states_disposition(self):
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

    def test_finalize_fills_missing_dimension_risk(self):
        draft = _minimal_draft(overall="medium")
        del draft["dimensions"][0]["risk"]
        del draft["overall_risk"]
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        assert result["dimensions"][0]["risk"] == "medium"
        assert result["overall_risk"] == "medium"
        assert result["schema_hint"] == "legal-review.v1"

    def test_finalize_normalizes_ids_and_parties_shape(self):
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

    def test_finalize_coerces_citation_id_alias(self):
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

    def test_rejects_hallucinated_citation(self):
        draft = _minimal_draft(cite_id="fake-id")
        _, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "fail"
        assert any("fake-id" in e for e in outcome.errors)

    def test_finalize_does_not_guess_missing_citation(self):
        draft = _minimal_draft(cite_id=None, overall="medium")
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        finding = result["dimensions"][0]["findings"][0]
        assert outcome.status == "fail"
        assert finding["citations"] == []
        assert any("needs citation id" in error for error in outcome.errors)

    def test_finalize_requires_source_for_strict_validation(self):
        draft = _minimal_draft()
        _, outcome = finalize_review(draft, evidence_packs=[_pack()])
        assert outcome.status == "fail"
        assert any("source_sections are required" in error for error in outcome.errors)

    def test_high_risk_finalize_passes(self):
        draft = _minimal_draft(overall="high")
        draft["dimensions"][0]["findings"][0]["suggestion"] = "必须整改"
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "pass"
        assert result["review_status"] == "machine_passed"
        assert result["human_review"]["status"] == "not_required"
        assert "必须整改" in result["report"]

    def test_high_risk_requires_suggestion(self):
        draft = _minimal_draft(overall="high")
        draft["dimensions"][0]["findings"][0]["suggestion"] = None
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "fail"
        assert any("requires suggestion" in error for error in outcome.errors)
        assert result["dimensions"][0]["findings"][0]["suggestion"] is None

    def test_empty_retrieval_blocks_conviction_without_cites(self):
        draft = _minimal_draft(cite_id=None, overall="medium")
        draft["dimensions"][0]["findings"][0]["risk"] = "medium"
        errors, _ = validate_review(draft, set(), retrieval_empty=True)
        assert any("needs citation id" in e for e in errors)

    def test_finalize_keeps_replace_edit(self):
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

    def test_finalize_rejects_edit_without_text_and_strips(self):
        draft = _minimal_draft()
        draft["dimensions"][0]["findings"][0]["edit"] = {"op": "replace", "text": ""}
        result, outcome = finalize_review(draft, evidence_packs=[_pack()], source_sections=_source())
        assert outcome.status == "fail"
        assert any("edit.text" in e for e in outcome.errors)
        assert result["dimensions"][0]["findings"][0]["edit"] == {"op": "none", "text": None}

    def test_finalize_rejects_quote_not_in_source(self):
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

    def test_finalize_grounds_quote_against_markdown_source(self):
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

    def test_finalize_rejects_ambiguous_edit_anchor(self):
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

    def test_finalize_tool_uses_retrieve_artifact(self):
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

    def test_finalize_accepts_flat_findings_json_string(self):
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

    def test_finalize_tool_retries_before_user_delivery(self):
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

    def test_finalize_tool_tolerates_trailing_junk_and_object_draft(self):
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

    def test_finalize_tool_delivers_parse_error_without_retry_loop(self):
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
    async def test_prepare_tool_resolves_upload_and_parses(self, tmp_path, monkeypatch):
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
    async def test_prepare_tool_defaults_to_uploaded_files(self, tmp_path, monkeypatch):
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
    async def test_prepare_tool_rejects_path_outside_thread(self, tmp_path, monkeypatch):
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

    def test_rejects_duplicate_finding_ids(self):
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
    async def test_retrieve_parallel_lanes_merge(self):
        from deerflow.config.knowledge_config import (
            KnowledgeConfig,
            KnowledgeScenarioConfig,
            ScenarioLaneConfig,
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
                        lanes=[
                            ScenarioLaneConfig(kinds=["policy"], tags=["statute", "national-law"], budget=4),
                            ScenarioLaneConfig(kinds=["policy"], tags=["company-policy"], budget=3),
                            ScenarioLaneConfig(kinds=["reference"], budget=2),
                            ScenarioLaneConfig(kinds=["case"], budget=3),
                        ],
                    )
                ]
            )
        )
        lane_hits = {
            "policy:statute-national-law": [
                {
                    "id": "law-1",
                    "source": "legal",
                    "kind": "policy",
                    "title": "law",
                    "snippet": "s",
                    "score": 0.9,
                }
            ],
            "policy:company-policy": [
                {
                    "id": "co-1",
                    "source": "legal",
                    "kind": "policy",
                    "title": "co",
                    "snippet": "s",
                    "score": 0.85,
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
                }
            ],
        }

        async def _fake_search_lane(_session, *, lane, **kwargs):
            return {
                "lane_id": lane.id,
                "hit_count": len(lane_hits.get(lane.id, [])),
                "items": lane_hits.get(lane.id, []),
                "trace_id": "trace-1",
                "knowledge_version": "kv",
                "fallback": None,
                "optional": False,
            }

        try:
            with (
                patch(
                    "deerflow.knowledge.service.list_accessible_spaces",
                    new=AsyncMock(return_value=[SimpleNamespace(id="legal", default_scenarios=["policy-review"])]),
                ),
                patch("deerflow.knowledge.service.search_lane", new=AsyncMock(side_effect=_fake_search_lane)),
            ):
                out = await retrieve_for_sections(
                    session=object(),
                    user_id="u1",
                    system_role="user",
                    sections=[{"id": "s1", "title": "s1", "body": "甲方应按约定及时付款并开具发票。"}],
                    spaces=["legal"],
                    scenario="policy-review",
                    top_k=4,
                )
        finally:
            set_knowledge_config(prev)

        assert set(out["allowed_ids"]) == {"law-1", "co-1", "ref-1", "case-1"}
        assert [item["id"] for item in out["packs"][0]["items"]] == [
            "law-1",
            "co-1",
            "ref-1",
            "case-1",
        ]
        assert len(out["section_results"][0]["lane_results"]) == 4
        assert out["quote_pool"][0]["quotes"]
        assert out["draft_scaffold"]["schema_hint"] == "legal-review.v1"
        assert out["draft_scaffold"]["dimensions"][0]["id"] == "s1"
        assert out["evidence_digest"][0]["evidence"][0]["id"] == "law-1"
        assert "snippet" in out["evidence_digest"][0]["evidence"][0]

    def test_merge_sections_caps_retrieve_fanout(self):
        sections = [{"id": f"section-{index}", "title": f"§{index}", "body": f"正文{index}。"} for index in range(1, 25)]
        merged = merge_sections(sections)
        assert len(merged) == 16
        assert all(section["id"].startswith("section-") for section in merged)

    def test_evidence_digest_exposes_snippets(self):
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

    def test_quote_pool_and_scaffold_are_stable(self):
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
    async def test_retrieve_tool_delegates_agent_scope_to_search(self):
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        from deerflow.knowledge.service import (
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
                patch("deerflow.knowledge.service.knowledge_extra_available", return_value=True),
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
    async def test_retrieve_async_restores_prior_prepare_sections(self):
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
                        "lane_results": [],
                    }
                ],
                "quote_pool": [{"section_id": "section-1", "quotes": ["甲方应按约定付款并及时开具发票。"]}],
                "draft_scaffold": {"schema_hint": "legal-review.v1"},
                "scenario": "policy-review",
            }

        with (
            patch("deerflow.config.knowledge_config.get_knowledge_config") as gk,
            patch("deerflow.knowledge.service.knowledge_extra_available", return_value=True),
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
    async def test_retrieve_async_restores_body_before_search(self):
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
            patch("deerflow.knowledge.service.knowledge_extra_available", return_value=True),
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

    def test_finalize_gate_includes_quote_pool_on_quote_errors(self):
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

    def test_idle_until_policy_tool_starts(self):
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

    def test_force_finalize_after_prepare(self):
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

    def test_after_model_ignores_tool_calls(self):
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

    def test_nudge_after_prepare_goes_to_finalize(self):
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

    def test_salvage_broken_finalize_without_llm_round(self):
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

    def test_exit_after_chinese_status_deliver(self):
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
