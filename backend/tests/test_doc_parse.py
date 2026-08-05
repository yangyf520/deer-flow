"""Unit tests for deerflow.doc_parse (slim pipeline + router)."""

from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.gateway.routers import doc as doc_router
from deerflow.doc_parse import pipeline
from deerflow.utils.file_conversion import ParseResult


def test_merge_concatenates_arrays():
    left = {"title": "Law A", "details": [{"segment_label": "1"}]}
    right = {"title": "", "details": [{"segment_label": "2"}], "extra": 1}
    merged = pipeline._merge(left, right)
    assert merged["title"] == "Law A"
    assert merged["details"] == [{"segment_label": "1"}, {"segment_label": "2"}]
    assert merged["extra"] == 1


def test_parse_json_via_langchain_helper():
    raw = '<think>x</think>\n```json\n{"title":"t","segments":[]}\n```'
    assert pipeline._parse_json(raw) == {"title": "t", "segments": []}


def test_parse_json_rejects_garbage():
    with pytest.raises(pipeline.DocParseError):
        pipeline._parse_json("not json at all")


def test_batches_packs_sections():
    blocks = ["a" * 100, "b" * 100, "c" * 100]
    batches = pipeline._batches(blocks, max_chars=250)
    assert len(batches) == 2


def test_batches_splits_oversized_single_block():
    block = "x" * 7000
    batches = pipeline._batches([block], max_chars=3000)
    assert len(batches) >= 3


def test_split_by_headings_atx():
    text = "Intro\n\n## Section A\n\nbody a\n\n## Section B\n\nbody b"
    parts = pipeline._split_by_headings(text)
    assert len(parts) >= 3


def test_split_by_headings_bold():
    text = "Intro\n\n**Chapter One**　text\n\n**Chapter Two**　more"
    parts = pipeline._split_by_headings(text)
    assert len(parts) == 3


def test_batches_limits_block_count():
    blocks = [f"{'x' * 500}-sec-{i}" for i in range(25)]
    joined_len = len("\n\n".join(blocks))
    assert joined_len > 6000
    batches = pipeline._batches(blocks, max_chars=6000, max_blocks=10)
    assert len(batches) >= 3
    assert all(len(b.split("\n\n")) <= 10 for b in batches)


def test_collect_warnings_empty_body_and_duplicate():
    warnings = pipeline._collect_warnings(
        {
            "title": "L",
            "details": [
                {"segment_label": "A", "body": "ok"},
                {"segment_label": "A", "body": ""},
            ],
        }
    )
    assert any("empty body" in w for w in warnings)
    assert any("duplicate" in w for w in warnings)


def test_grounding_accepts_whitespace_normalized_match():
    source = "第一条　为了保护个人信息权益，制定本法。"
    assert pipeline._body_grounded_in_source("为了保护个人信息权益，制定本法。", source)


def test_grounding_rejects_paraphrase():
    source = "第一条　为了保护个人信息权益，制定本法。"
    assert not pipeline._body_grounded_in_source("这是模型编造的摘要内容。", source)


def test_collect_warnings_grounding():
    source = "**第一条**　原文内容在这里。"
    warnings = pipeline._collect_warnings(
        {
            "title": "L",
            "details": [
                {"segment_label": "第一条", "body": "原文内容在这里。"},
                {"segment_label": "第二条", "body": "模型改写过的句子。"},
            ],
        },
        source_text=source,
    )
    assert not any("第一条" in w for w in warnings)
    assert any("paraphrase" in w for w in warnings)


def test_find_row_no():
    source = "header\n\n## Section\n\nclause one\n\nclause two"
    assert pipeline._find_row_no("clause one", source) == 5


def test_attach_row_no_assigns_unique_uuid_ids():
    import uuid as uuid_mod

    data = {
        "title": "L",
        "details": [
            {"segment_label": "第1条", "body": "正文一"},
            {"segment_label": "第2条", "body": "正文二"},
        ],
    }
    pipeline._attach_row_no(data, source_text="ignored")
    ids = [detail["row_no"] for detail in data["details"]]
    assert all(isinstance(row_id, str) and row_id for row_id in ids)
    assert len(set(ids)) == 2
    for row_id in ids:
        uuid_mod.UUID(row_id)


def test_attach_row_no_preserves_llm_uuid_and_replaces_integer():
    existing = "d34f6874-7417-49ca-8aaf-f8aab4e63b0a"
    data = {
        "details": [
            {"body": "one", "row_no": existing},
            {"body": "two", "row_no": 1},
            {"body": "three"},
        ],
    }
    pipeline._attach_row_no(data, source_text="line one\nline two\nline three")
    assert data["details"][0]["row_no"] == existing
    assert data["details"][1]["row_no"] != "1"
    assert data["details"][2]["row_no"] != existing
    import uuid as uuid_mod

    for detail in data["details"][1:]:
        uuid_mod.UUID(detail["row_no"])
    assert len({d["row_no"] for d in data["details"]}) == 3


def test_parse_document_runs_batches_in_parallel(monkeypatch):
    import re

    monkeypatch.setattr(
        pipeline,
        "_to_markdown",
        lambda data, filename: (ParseResult(text="# T\n\nclause one", parse_quality="ok"), "docling"),
    )
    monkeypatch.setattr(pipeline, "_markdown_blocks", lambda text: ["a", "b", "c"])
    monkeypatch.setattr(
        pipeline,
        "resolve_parse_batch_limits",
        lambda **kwargs: pipeline.ParseBatchLimits(max_chars=6000, max_blocks=10, max_concurrent=8),
    )
    monkeypatch.setattr(
        pipeline,
        "_batches",
        lambda blocks, max_chars, max_blocks=None: blocks,
    )

    responses = [
        '{"title":"Doc","details":[{"segment_label":"1","body":"a"}]}',
        '{"title":"","details":[{"segment_label":"2","body":"b"}]}',
        '{"title":"","details":[{"segment_label":"3","body":"c"}]}',
    ]
    started: list[int] = []
    finished: list[int] = []

    async def fake_llm(**kwargs):
        m = re.search(r"batch (\d+)/", kwargs["user_content"])
        assert m
        i = int(m.group(1)) - 1
        started.append(i)
        await asyncio.sleep(0.05)
        finished.append(i)
        return responses[i]

    monkeypatch.setattr(pipeline, "run_oneshot_llm", fake_llm)
    monkeypatch.setattr(pipeline, "create_chat_model", lambda **kwargs: object())

    result = asyncio.run(
        pipeline.parse_document(
            data=b"ignored",
            filename="law.md",
            segment_prompt="Return {title, details[]}",
            app_config=SimpleNamespace(),
        )
    )
    assert len(result.data["details"]) == 3
    assert len(started) == 3
    assert len(finished) == 3
    assert result.meta.parse_backend == "docling"


def test_split_pipl_style_markdown_block_count():
    text = "**法**\n\n**第一章**　总则\n\n" + "\n\n".join(f"**第{i}条**　内容{i}" for i in range(1, 21))
    blocks = pipeline._markdown_blocks(text)
    assert len(blocks) >= 15
    batches = pipeline._batches(blocks, max_chars=100_000, max_blocks=20)
    assert len(batches) >= 2


def test_resolve_parse_batch_limits_from_model_max_tokens():
    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    app_config = AppConfig(
        models=[
            ModelConfig(
                name="default",
                display_name="Default",
                use="langchain_openai:ChatOpenAI",
                model="test",
                max_tokens=16384,
            )
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )
    limits = pipeline.resolve_parse_batch_limits(app_config=app_config)
    assert limits.max_chars == 16384
    assert limits.max_blocks == 20
    assert limits.max_concurrent == 8


def test_validate_schema_fails():
    schema = {"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}}
    with pytest.raises(pipeline.DocParseError, match="validation failed"):
        pipeline._validate_schema({"other": 1}, schema)


def test_to_markdown_text_fast_path():
    parsed, backend = pipeline._to_markdown(b"# Title\n\nbody", "law.md")
    assert backend == "text"
    assert parsed.parse_quality == "ok"
    assert "Title" in parsed.text


def test_to_markdown_docx_prefers_markitdown(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "parse_markitdown_bytes",
        lambda data, filename: ParseResult(text="**第1条** 内容", parse_quality="ok"),
    )

    def fail_docling(*args, **kwargs):
        raise AssertionError("Docling should not run when MarkItDown succeeds")

    monkeypatch.setattr(pipeline, "parse_file_bytes_with_fallback", fail_docling)
    parsed, backend = pipeline._to_markdown(b"docx-bytes", "law.docx")
    assert backend == "markitdown"
    assert parsed.text.startswith("**第1条**")


def test_parse_document_happy_path(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "_to_markdown",
        lambda data, filename: (
            ParseResult(text="# T\n\nclause one\n\nclause two", parse_quality="ok"),
            "docling",
        ),
    )
    monkeypatch.setattr(pipeline, "_markdown_blocks", lambda text: ["clause one", "clause two"])
    monkeypatch.setattr(
        pipeline,
        "resolve_parse_batch_limits",
        lambda **kwargs: pipeline.ParseBatchLimits(max_chars=6000, max_blocks=None, max_concurrent=8),
    )
    monkeypatch.setattr(
        pipeline,
        "_batches",
        lambda blocks, max_chars, max_blocks=None: ["clause one", "clause two"],
    )

    responses = [
        '{"title":"Doc","details":[{"segment_label":"1","body":"clause one"}]}',
        '{"title":"","details":[{"segment_label":"2","body":"clause two"}]}',
    ]

    async def fake_llm(**kwargs):
        import re

        assert kwargs["run_name"] == "doc_parse"
        assert kwargs["system_instruction"] == "Return {title, details[]}"
        m = re.search(r"batch (\d+)/", kwargs["user_content"])
        i = int(m.group(1)) - 1
        return responses[i]

    monkeypatch.setattr(pipeline, "run_oneshot_llm", fake_llm)
    monkeypatch.setattr(pipeline, "create_chat_model", lambda **kwargs: object())

    result = asyncio.run(
        pipeline.parse_document(
            data=b"ignored",
            filename="law.md",
            segment_prompt="Return {title, details[]}",
            app_config=SimpleNamespace(),
        )
    )
    assert result.data["title"] == "Doc"
    assert len(result.data["details"]) == 2
    assert result.meta.batch_count == 2
    row_ids = [detail["row_no"] for detail in result.data["details"]]
    assert all(isinstance(row_id, str) and row_id for row_id in row_ids)
    assert len(set(row_ids)) == len(row_ids)


def test_parse_document_requires_prompt(monkeypatch):
    with pytest.raises(pipeline.DocParseError, match="segment_prompt"):
        asyncio.run(
            pipeline.parse_document(
                data=b"x",
                filename="x.pdf",
                segment_prompt="  ",
                app_config=SimpleNamespace(),
            )
        )


def test_parse_document_parse_failure(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "_to_markdown",
        lambda data, filename: (ParseResult(text="", parse_quality="failed", error="boom"), "docling"),
    )
    with pytest.raises(pipeline.DocParseError, match="boom"):
        asyncio.run(
            pipeline.parse_document(
                data=b"x",
                filename="x.pdf",
                segment_prompt="p",
                app_config=SimpleNamespace(),
            )
        )


def _upload(content: bytes, filename: str = "doc.txt") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


def test_router_empty_file():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            doc_router.parse_doc.__wrapped__(
                request=None,
                file=_upload(b""),
                segment_prompt="p",
                output_schema=None,
                config=SimpleNamespace(),
            )
        )
    assert exc.value.status_code == 400


def test_router_success(monkeypatch):
    async def fake_parse(**kwargs):
        from deerflow.doc_parse.contract import DocParseMeta, DocParseResponse

        assert kwargs["segment_prompt"] == "do it"
        return DocParseResponse(
            data={"title": "t"},
            meta=DocParseMeta(source_filename="a.md", segment_prompt_hash="sha256:abc", block_count=1, batch_count=1),
        )

    monkeypatch.setattr(doc_router, "parse_document", fake_parse)
    result = asyncio.run(
        doc_router.parse_doc.__wrapped__(
            request=None,
            file=_upload(b"# hi", "a.md"),
            segment_prompt="do it",
            output_schema=None,
            config=SimpleNamespace(),
        )
    )
    assert result.data["title"] == "t"


def test_router_maps_error(monkeypatch):
    async def boom(**kwargs):
        raise pipeline.DocParseError("bad json", status_code=422)

    monkeypatch.setattr(doc_router, "parse_document", boom)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            doc_router.parse_doc.__wrapped__(
                request=None,
                file=_upload(b"x", "x.txt"),
                segment_prompt="p",
                output_schema=None,
                config=SimpleNamespace(),
            )
        )
    assert exc.value.status_code == 422
