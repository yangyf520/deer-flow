"""Core knowledge tests: ACL, RAG assembly, API gate."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from llama_index.core import Document
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import HierarchicalNodeParser, get_leaf_nodes
from starlette.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import knowledge as knowledge_router
from deerflow.knowledge.rag import ContextualTitleTransform, resolve_scenario
from deerflow.knowledge.service import (
    resolve_space_role,
    role_at_least,
)


def test_pg_params_prefer_connection_string():
    from deerflow.config.knowledge_config import KnowledgeVectorStoreConfig
    from deerflow.knowledge import rag

    cfg = KnowledgeVectorStoreConfig(
        type="pgvector",
        connection_string="postgresql://u:secret@db.example:6543/kb",
        host="ignored",
        database="ignored",
    )
    params = rag._pg_params_from_vector_config(cfg)
    assert params["host"] == "db.example"
    assert params["port"] == 6543
    assert params["database"] == "kb"
    assert params["user"] == "u"
    assert params["password"] == "secret"


def test_pg_params_use_discrete_fields_when_no_url():
    from deerflow.config.knowledge_config import KnowledgeVectorStoreConfig
    from deerflow.knowledge import rag

    cfg = KnowledgeVectorStoreConfig(
        type="pgvector",
        host="127.0.0.1",
        port=5433,
        database="vectors",
        user="kb",
        password="pw",
    )
    params = rag._pg_params_from_vector_config(cfg)
    assert params == {
        "host": "127.0.0.1",
        "port": 5433,
        "database": "vectors",
        "user": "kb",
        "password": "pw",
    }


def test_app_config_loads_knowledge_vector_store(tmp_path):
    """AppConfig.from_file must apply knowledge.vector_store (not leave chroma default)."""
    from deerflow.config.app_config import AppConfig
    from deerflow.config.knowledge_config import get_knowledge_config, set_knowledge_config

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "\n".join(
            [
                "sandbox:",
                "  use: deerflow.sandbox.local:LocalSandboxProvider",
                "knowledge:",
                "  enabled: true",
                "  vector_store:",
                "    type: pgvector",
                "    connection_string: postgresql://u:p@localhost:5432/deerflow",
                "    table_name: knowledge_embed",
            ]
        ),
        encoding="utf-8",
    )
    prev = get_knowledge_config()
    try:
        AppConfig.from_file(str(cfg))
        loaded = get_knowledge_config()
        assert loaded.enabled is True
        assert loaded.vector_store.type == "pgvector"
        assert loaded.vector_store.table_name == "knowledge_embed"
        assert "postgresql://" in loaded.vector_store.connection_string
    finally:
        set_knowledge_config(prev)


def _api_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(knowledge_router.router)
    return app


def test_role_at_least():
    assert role_at_least("admin", "viewer")
    assert not role_at_least("viewer", "editor")


@pytest.mark.asyncio
async def test_list_documents_filters_by_kind():
    from deerflow.knowledge import service as knowledge_service

    session = AsyncMock()
    rows = [
        SimpleNamespace(
            id="d1",
            space_id="legal",
            title="a",
            kind="policy",
            tags=[],
            language="zh-CN",
            sensitivity="internal",
            status="ready",
            source_filename="a.docx",
            source_uri="",
            content_type="application/octet-stream",
            byte_size=1,
            job_phase="done",
            progress=100,
            parse_quality=None,
            parse_error=None,
            error_message=None,
            created_by="u1",
            effective_from=None,
            effective_to=None,
            created_at=None,
            updated_at=None,
        )
    ]

    page = MagicMock()
    page.scalars.return_value.all.return_value = rows
    session.scalar = AsyncMock(return_value=1)
    session.execute = AsyncMock(return_value=page)

    with patch(
        "deerflow.knowledge.service.resolve_user_display_names",
        new=AsyncMock(return_value={"u1": "u1"}),
    ):
        items, total = await knowledge_service.list_documents(session, "legal", kind="policy", limit=20, offset=0)

    assert total == 1
    assert len(items) == 1
    assert items[0].kind == "policy"
    session.scalar.assert_awaited()
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_open_space_grants_viewer():
    space = SimpleNamespace(id="legal", owner_user_id="other", access="open")
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    role = await resolve_space_role(session, user_id="u1", system_role="user", space=space)
    assert role == "viewer"


@pytest.mark.asyncio
async def test_private_space_denies_non_owner():
    space = SimpleNamespace(id="legal", owner_user_id="other", access="private")
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=user_result)
    role = await resolve_space_role(session, user_id="u1", system_role="user", space=space, dept_ids=["hr"])
    assert role is None


@pytest.mark.asyncio
async def test_private_space_uses_direct_user_grant():
    space = SimpleNamespace(id="legal", owner_user_id="other", access="private")
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalars.return_value.all.return_value = ["editor"]
    session.execute = AsyncMock(return_value=user_result)

    role = await resolve_space_role(session, user_id="u1", system_role="user", space=space)

    assert role == "editor"
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_space_uses_dept_grant():
    space = SimpleNamespace(id="legal", owner_user_id="other", access="private")
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalars.return_value.all.return_value = []
    dept_result = MagicMock()
    dept_result.scalars.return_value.all.return_value = ["viewer"]
    session.execute = AsyncMock(side_effect=[user_result, dept_result])

    role = await resolve_space_role(session, user_id="u1", system_role="user", space=space, dept_ids=["hr"])

    assert role == "viewer"
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_upsert_dept_grant_stores_upstream_subject_id():
    from deerflow.knowledge import service as knowledge_service

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    out = await knowledge_service.upsert_grant(
        session,
        space_id="legal",
        subject_type="dept",
        subject_id="upstream-dept-hr",
        role="viewer",
        granted_by="admin-1",
    )

    assert out.subject_type == "dept"
    assert out.subject_id == "upstream-dept-hr"
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_list_documents_filters_by_query():
    from deerflow.knowledge import service as knowledge_service

    session = AsyncMock()
    rows = []
    page = MagicMock()
    page.scalars.return_value.all.return_value = rows
    session.scalar = AsyncMock(return_value=0)
    session.execute = AsyncMock(return_value=page)

    with patch(
        "deerflow.knowledge.service.resolve_user_display_names",
        new=AsyncMock(return_value={}),
    ):
        items, total = await knowledge_service.list_documents(session, "legal", q="handbook", limit=20, offset=0)

    assert total == 0
    assert items == []
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_import_dedupes_same_checksum():
    from deerflow.knowledge import service as knowledge_service

    existing = SimpleNamespace(
        id="doc-old",
        space_id="legal",
        title="t",
        kind="policy",
        language="zh-CN",
        sensitivity="internal",
        status="ready",
        source_filename="a.docx",
        source_uri="file:///x",
        content_type="application/octet-stream",
        byte_size=3,
        checksum_sha256="deadbeef",
        external_id=None,
        tags=[],
        attrs={},
        effective_from=None,
        effective_to=None,
        job_phase="ready",
        progress=100,
        parse_quality="ok",
        parse_error=None,
        error_message=None,
        created_by="u1",
        created_at=None,
        updated_at=None,
    )
    space = SimpleNamespace(id="legal", allowed_kinds=[])
    session = AsyncMock()
    session.get = AsyncMock(return_value=space)
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing
    session.execute = AsyncMock(return_value=result)

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("deerflow.knowledge.service.hashlib.sha256") as sha,
        patch("deerflow.knowledge.service.asyncio.create_task") as create_task,
    ):
        sha.return_value.hexdigest.return_value = "deadbeef"
        out = await knowledge_service.import_document(
            factory,
            space_id="legal",
            user_id="u1",
            filename="a.docx",
            content_type="application/octet-stream",
            data=b"abc",
            kind="policy",
        )
        assert out.doc_id == "doc-old"
        assert out.deduped is True
        create_task.assert_not_called()


def test_knowledge_fk_ondelete_cascade():
    from deerflow.persistence.knowledge.model import KnowledgeDocumentRow, KnowledgeGrantRow

    doc_fk = next(c for c in KnowledgeDocumentRow.__table__.constraints if c.name == "fk_knowledge_documents_space_id")
    grant_fk = next(c for c in KnowledgeGrantRow.__table__.constraints if c.name == "fk_knowledge_grants_space_id")
    assert doc_fk.ondelete == "CASCADE"
    assert grant_fk.ondelete == "CASCADE"


@pytest.mark.asyncio
async def test_delete_space_clears_vectors_then_db():
    from deerflow.knowledge import service as knowledge_service

    space = SimpleNamespace(id="legal", owner_user_id="u1", access="private")
    doc = SimpleNamespace(id="d1", space_id="legal", source_uri="")
    session = AsyncMock()
    session.get = AsyncMock(return_value=space)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [doc]
    session.execute = AsyncMock(return_value=result)
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    async def _to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with (
        patch("deerflow.knowledge.service.resolve_space_role", new=AsyncMock(return_value="admin")),
        patch("deerflow.knowledge.service.asyncio.to_thread", side_effect=_to_thread),
        patch("deerflow.knowledge.service.delete_document_vectors") as del_doc,
        patch("deerflow.knowledge.service.delete_space_vectors") as del_vec,
    ):
        del_doc.return_value = 1
        del_vec.return_value = 3
        await knowledge_service.delete_space(session, space_id="legal", user_id="u1", system_role="user")
        del_doc.assert_called_once_with(space_id="legal", doc_id="d1")
        del_vec.assert_called_once_with(space_id="legal")
        session.delete.assert_called_once_with(space)


def test_delete_pgvector_predicate_covers_doc_id_fields():
    """Ensure delete helper targets ref_doc_id and metadata.doc_id (not only node list)."""
    import inspect

    from deerflow.knowledge import rag

    src = inspect.getsource(rag._delete_pgvector_rows_for_doc)
    assert 'metadata_["ref_doc_id"]' in src
    assert 'metadata_["doc_id"]' in src


def test_rerank_assembles_configured_postprocessor():
    """Rerank loads LlamaIndex postprocessor via rerank_use — swap models without custom SDK glue."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeRetrievalConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import rag

    prev = get_knowledge_config()
    try:
        set_knowledge_config(
            KnowledgeConfig(
                retrieval=KnowledgeRetrievalConfig(
                    rerank=True,
                    rerank_use="llama_index.postprocessor.dashscope_rerank:DashScopeRerank",
                    rerank_model="qwen3-rerank",
                    rerank_api_key="sk-rerank-test",
                    top_k=2,
                )
            )
        )
        fake_cls = MagicMock()
        instance = MagicMock()
        instance.postprocess_nodes.return_value = [SimpleNamespace(score=0.9)]
        fake_cls.return_value = instance
        with patch("deerflow.reflection.resolvers.resolve_class", return_value=fake_cls):
            out = rag._apply_rerank([SimpleNamespace(score=0.1)], query="E4", top_n=2)
        fake_cls.assert_called_once()
        kwargs = fake_cls.call_args.kwargs
        assert kwargs.get("model") == "qwen3-rerank"
        assert kwargs.get("api_key") == "sk-rerank-test"
        assert kwargs.get("top_n") == 1  # min(top_n, len(nodes))
        instance.postprocess_nodes.assert_called_once()
        assert out[0].score == 0.9
    finally:
        set_knowledge_config(prev)


def test_embed_openai_assembles_via_use():
    from unittest.mock import MagicMock, patch

    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeEmbedConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import rag

    prev = get_knowledge_config()
    try:
        set_knowledge_config(
            KnowledgeConfig(
                embed=KnowledgeEmbedConfig(
                    use="llama_index.embeddings.openai:OpenAIEmbedding",
                    model="text-embedding-3-small",
                    api_key="sk-test",
                    api_base="https://gateway.example.com/v1",
                    embed_dim=1536,
                )
            )
        )
        fake_cls = MagicMock(return_value=MagicMock(name="embed"))
        with patch("deerflow.reflection.resolvers.resolve_class", return_value=fake_cls):
            rag.get_embed_model()
        fake_cls.assert_called_once()
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["model_name"] == "text-embedding-3-small"
        assert "model" not in kwargs
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["api_base"] == "https://gateway.example.com/v1"
    finally:
        set_knowledge_config(prev)


def test_embed_openai_compatible_model_uses_model_name():
    from deerflow.config.knowledge_config import KnowledgeEmbedConfig

    cfg = KnowledgeEmbedConfig(
        use="llama_index.embeddings.openai:OpenAIEmbedding",
        model="text-embedding-v3",
        api_key="sk-test",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    kwargs = cfg.ctor_kwargs()
    assert kwargs["model_name"] == "text-embedding-v3"
    assert "model" not in kwargs
    assert kwargs["embed_batch_size"] == 10
    assert kwargs["dimensions"] == 1536  # default KnowledgeEmbedConfig.embed_dim


def test_embed_legacy_base_url_aliases_to_api_base(monkeypatch):
    from deerflow.config.knowledge_config import KnowledgeEmbedConfig

    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    cfg = KnowledgeEmbedConfig(
        use="llama_index.embeddings.openai:OpenAIEmbedding",
        model="emb",
        base_url="https://legacy.example/v1",
    ).resolved()
    assert cfg.api_base == "https://legacy.example/v1"
    assert "base_url" not in cfg.ctor_kwargs()


def test_embed_provider_defaults_to_azure_or_openai(monkeypatch):
    from deerflow.config.knowledge_config import KnowledgeEmbedConfig

    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    azure = KnowledgeEmbedConfig(provider="azure", model="emb").resolved()
    assert "azure_openai" in azure.use.lower()
    assert azure.model == "emb"

    openai = KnowledgeEmbedConfig(provider="openai", model="emb").resolved()
    assert openai.use.endswith("OpenAIEmbedding")
    assert "azure" not in openai.use.lower()


def test_query_llm_assembles_via_use():
    from unittest.mock import MagicMock, patch

    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeQueryLlmConfig,
        KnowledgeRetrievalConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import rag

    prev = get_knowledge_config()
    try:
        set_knowledge_config(
            KnowledgeConfig(
                retrieval=KnowledgeRetrievalConfig(
                    query_llm=KnowledgeQueryLlmConfig(
                        enabled=True,
                        use="llama_index.llms.openai:OpenAI",
                        model="gpt-4o-mini",
                        api_key="sk-test",
                        api_base="https://example.com/v1",
                    )
                )
            )
        )
        fake_cls = MagicMock(return_value=MagicMock(name="llm"))
        mock_settings = MagicMock()
        mock_settings.embed_model = MagicMock()
        mock_settings.llm = None
        mock_settings._embed_model = mock_settings.embed_model
        mock_settings._llm = None
        with (
            patch("llama_index.core.Settings", mock_settings),
            patch("deerflow.reflection.resolvers.resolve_class", return_value=fake_cls),
        ):
            assert rag.ensure_llama_settings() is True
        fake_cls.assert_called_once()
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["api_base"] == "https://example.com/v1"
        assert mock_settings.llm is not None
    finally:
        set_knowledge_config(prev)


def test_knowledge_extra_does_not_require_chromadb():
    from deerflow.knowledge.service import knowledge_extra_available

    assert knowledge_extra_available() is True


def test_ingestion_pipeline_leaves():
    from deerflow.config.knowledge_config import get_knowledge_config

    ingest = get_knowledge_config().ingest
    text = "# 第一章\n\n" + ("段落内容。" * 80) + "\n\n## 第二节\n\n" + ("细节说明。" * 40)
    docs = [Document(text=text, metadata={"title": "测试"})]
    parser = HierarchicalNodeParser.from_defaults(
        chunk_sizes=list(ingest.chunk_sizes),
        chunk_overlap=ingest.chunk_overlap,
    )
    nodes = IngestionPipeline(transformations=[parser, ContextualTitleTransform()]).run(documents=docs, show_progress=False)
    leaves = get_leaf_nodes(nodes)
    assert len(nodes) >= len(leaves) >= 1
    assert any("测试" in (n.get_content() or "") for n in leaves)


def test_build_node_parser_uses_llamaindex_hierarchical_by_default():
    from llama_index.core import Document
    from llama_index.core.node_parser import HierarchicalNodeParser, MarkdownNodeParser

    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeIngestConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import rag

    prev = get_knowledge_config()
    try:
        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="auto")))
        # Plain prose (no markdown headings) → HierarchicalNodeParser
        parser = rag._build_node_parser([Document(text="hello world without headings")])
        assert isinstance(parser, HierarchicalNodeParser)

        # Markdown headings → MarkdownNodeParser in auto mode
        parser = rag._build_node_parser([Document(text="# hello\n\nworld")])
        assert isinstance(parser, MarkdownNodeParser)

        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="markdown")))
        parser = rag._build_node_parser([Document(text="# hello\n\nworld")])
        assert isinstance(parser, MarkdownNodeParser)

        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="hierarchical")))
        parser = rag._build_node_parser([Document(text="# hello\n\nworld")])
        assert isinstance(parser, HierarchicalNodeParser)
    finally:
        set_knowledge_config(prev)


def test_build_node_parser_kind_faq_vs_policy():
    from llama_index.core import Document
    from llama_index.core.node_parser import HierarchicalNodeParser, SentenceSplitter

    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeIngestConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import rag

    prev = get_knowledge_config()
    try:
        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="auto", chunk_sizes=[1024, 256])))
        plain = [Document(text="Q: 如何报销？\nA: 走财务系统提交票据即可。")]
        faq_parser = rag._build_node_parser(plain, kind="faq")
        assert isinstance(faq_parser, SentenceSplitter)
        assert faq_parser.chunk_size == 1024

        policy_parser = rag._build_node_parser(
            [Document(text="第一章 总则。" + ("条款内容。" * 40))],
            kind="policy",
        )
        assert isinstance(policy_parser, HierarchicalNodeParser)
    finally:
        set_knowledge_config(prev)


def test_compute_precision_recall_at_k():
    from deerflow.knowledge.rag import compute_precision_recall_at_k

    p, r = compute_precision_recall_at_k(
        retrieved_doc_ids=["a", "b", "c"],
        relevant_doc_ids=["a", "d"],
        k=3,
    )
    assert p == pytest.approx(1 / 3)
    assert r == pytest.approx(0.5)

    p2, r2 = compute_precision_recall_at_k(
        retrieved_doc_ids=["a", "b"],
        relevant_doc_ids=["a", "b"],
        k=2,
    )
    assert p2 == 1.0 and r2 == 1.0

    p3, r3 = compute_precision_recall_at_k(
        retrieved_doc_ids=["x"],
        relevant_doc_ids=[],
        k=5,
    )
    assert p3 == 0.0 and r3 == 0.0


def test_knowledge_docling_deps_declared():
    """Docling ships in the knowledge extra for document parse."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    knowledge = "\n".join(data["project"]["optional-dependencies"]["knowledge"]).lower()
    assert "llama-index-core" in knowledge
    assert "docling" in knowledge
    assert "llama-index-node-parser-docling" not in knowledge
    assert "llama-index-readers-docling" not in knowledge


def test_sanitize_media_and_evidence_snippet():
    from deerflow.knowledge import rag

    raw = "前言\n\ndata:image/jpeg;base64," + ("A" * 200) + "\n\n生物特征数据是指面部图像或指纹。"
    cleaned = rag.sanitize_media(raw)
    assert "base64" not in cleaned
    assert "[image]" in cleaned
    assert rag.annotate_block_type("| a | b |\n| --- | --- |\n| 1 | 2 |") == "table"
    snip = rag.format_evidence_snippet(raw + ("填充。" * 400), "生物特征数据", max_chars=200)
    assert "base64" not in snip
    assert len(snip) <= 220
    assert "生物特征" in snip or "面部" in snip


def test_score_cutoff_filters_low_rerank_scores():
    from types import SimpleNamespace

    from deerflow.knowledge import rag

    nodes = [
        SimpleNamespace(score=0.9, node=SimpleNamespace()),
        SimpleNamespace(score=0.2, node=SimpleNamespace()),
    ]
    kept = rag._apply_score_cutoff(nodes, 0.35)
    assert len(kept) == 1
    assert kept[0].score == 0.9


def test_build_retriever_wraps_parent_expand_when_enabled():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeRetrievalConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import rag

    prev = get_knowledge_config()
    try:
        set_knowledge_config(
            KnowledgeConfig(
                retrieval=KnowledgeRetrievalConfig(
                    hybrid=False,
                    bm25=False,
                    rerank=False,
                    parent_expand=True,
                    fusion_num_queries=1,
                )
            )
        )
        docstore = SimpleNamespace(docs={"n1": object()})
        vector_store = MagicMock()
        index = MagicMock()
        index.as_retriever.return_value = MagicMock(name="vector")
        amalg = MagicMock(name="auto_merge")
        fusion = MagicMock(name="fusion")
        with (
            patch("deerflow.knowledge.rag.load_docstore", return_value=docstore),
            patch("deerflow.knowledge.rag.get_vector_store", return_value=vector_store),
            patch("deerflow.knowledge.rag.get_embed_model", return_value=MagicMock()),
            patch("llama_index.core.StorageContext.from_defaults", return_value=MagicMock()),
            patch("llama_index.core.VectorStoreIndex.from_vector_store", return_value=index),
            patch("llama_index.core.retrievers.QueryFusionRetriever", return_value=fusion),
            patch("llama_index.core.retrievers.AutoMergingRetriever", return_value=amalg) as auto_cls,
            patch("deerflow.knowledge.rag.ensure_llama_settings", return_value=False),
        ):
            out = rag._build_retriever(space_id="s1", retrieve_n=10, num_queries=1)
        assert out is amalg
        auto_cls.assert_called_once()
    finally:
        set_knowledge_config(prev)


def test_scenario_pack_defaults():
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
                KnowledgeScenarioConfig(type="general-qa", top_k=8, score=0.35),
                KnowledgeScenarioConfig(type="policy-review", top_k=10, score=0.3),
            ]
        )
    )
    try:
        pack = resolve_scenario(request_scenario=None, space_default_scenarios=["policy-review"])
        assert pack.id == "policy-review"
        assert pack.top_k == 10
    finally:
        set_knowledge_config(prev)


def test_search_requires_auth():
    client = TestClient(_api_app())
    assert client.post("/api/knowledge/v1/search", json={"query": "hello"}).status_code == 401


@pytest.mark.asyncio
async def test_search_applies_scenario_pack():
    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeScenarioConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import service as knowledge_service

    prev = get_knowledge_config()
    set_knowledge_config(
        KnowledgeConfig(
            scenarios=[
                KnowledgeScenarioConfig(type="general-qa", top_k=8, score=0.35),
                KnowledgeScenarioConfig(
                    type="policy-review",
                    top_k=10,
                    score=0.3,
                    fusion_num_queries=1,
                ),
            ]
        )
    )
    space = SimpleNamespace(
        id="legal",
        default_scenarios=["policy-review"],
        name="legal",
        description=None,
        access="open",
        owner_user_id="u1",
        allowed_kinds=[],
        created_at=None,
        updated_at=None,
    )
    try:
        with (
            patch(
                "deerflow.knowledge.service.list_accessible_spaces",
                new=AsyncMock(return_value=[space]),
            ),
            patch("deerflow.knowledge.service.search_space") as search_space,
        ):
            search_space.return_value = [
                {
                    "id": "n1",
                    "source": "chunk",
                    "kind": "policy",
                    "title": "t",
                    "snippet": "s",
                    "score": 0.1,
                    "citable_as": "t",
                    "metadata": {},
                }
            ]
            pack = await knowledge_service.search(
                AsyncMock(),
                user_id="u1",
                system_role="user",
                query="E4级产品",
                spaces=["legal"],
                kinds=None,
                top_k=None,
                scenario=None,
            )
            assert len(pack.items) == 1
            # No lanes → single path with scenario top_k / score
            assert search_space.call_args.kwargs["kinds"] is None
            assert search_space.call_args.kwargs["top_k"] == 10
            assert search_space.call_args.kwargs["similarity_cutoff"] == 0.3
            assert search_space.call_args.kwargs["fusion_queries"] == 1
    finally:
        set_knowledge_config(prev)


@pytest.mark.asyncio
async def test_search_merges_scenario_lanes():
    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeScenarioConfig,
        ScenarioLaneConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge import service as knowledge_service

    prev = get_knowledge_config()
    set_knowledge_config(
        KnowledgeConfig(
            scenarios=[
                KnowledgeScenarioConfig(
                    type="policy-review",
                    top_k=4,
                    score=0.3,
                    merge_mode="slot_then_rrf",
                    lanes=[
                        ScenarioLaneConfig(kinds=["policy"], tags=["statute"], budget=2),
                        ScenarioLaneConfig(kinds=["case"], budget=2),
                    ],
                )
            ]
        )
    )
    space = SimpleNamespace(id="legal", default_scenarios=["policy-review"])

    async def _fake_lane(_session, *, lane, **kwargs):
        item = {
            "id": f"{lane.id}-1",
            "source": "chunk",
            "kind": lane.kinds[0],
            "title": lane.id,
            "snippet": "s",
            "score": 0.9,
            "metadata": {},
        }
        return {
            "lane_id": lane.id,
            "hit_count": 1,
            "items": [item],
            "trace_id": "t-lane",
            "knowledge_version": "kv",
            "fallback": None,
            "optional": False,
        }

    try:
        with (
            patch(
                "deerflow.knowledge.service.list_accessible_spaces",
                new=AsyncMock(return_value=[space]),
            ),
            patch("deerflow.knowledge.service.search_lane", new=AsyncMock(side_effect=_fake_lane)),
        ):
            pack = await knowledge_service.search(
                AsyncMock(),
                user_id="u1",
                system_role="user",
                query="clause",
                spaces=["legal"],
                kinds=None,
                top_k=None,
                scenario="policy-review",
            )
        assert {it.id for it in pack.items} == {"policy:statute-1", "case-1"}
        assert pack.metadata.get("merge_mode") == "slot_then_rrf"
        assert len(pack.metadata.get("lanes") or []) == 2
    finally:
        set_knowledge_config(prev)


@pytest.mark.asyncio
async def test_search_empty_spaces_returns_no_hits():
    from deerflow.knowledge import service as knowledge_service

    space = SimpleNamespace(id="legal", default_scenarios=["policy-review"])
    with (
        patch(
            "deerflow.knowledge.service.list_accessible_spaces",
            new=AsyncMock(return_value=[space]),
        ),
        patch("deerflow.knowledge.service.search_space") as search_space,
    ):
        pack = await knowledge_service.search(
            AsyncMock(),
            user_id="u1",
            system_role="user",
            query="hello",
            spaces=[],
            kinds=None,
            top_k=None,
            scenario=None,
        )
        assert pack.items == []
        search_space.assert_not_called()


def test_set_agent_knowledge_defaults_empty_spaces():
    from deerflow.knowledge.service import (
        get_agent_knowledge_defaults,
        reset_agent_knowledge_defaults,
        set_agent_knowledge_defaults,
    )

    token = set_agent_knowledge_defaults(spaces=[], scenario=None)
    assert get_agent_knowledge_defaults() == {"spaces": []}
    reset_agent_knowledge_defaults(token)


def test_agent_knowledge_scope_is_a_hard_ceiling():
    from deerflow.knowledge.service import (
        reset_agent_knowledge_defaults,
        resolve_agent_knowledge_scope,
        set_agent_knowledge_defaults,
    )

    token = set_agent_knowledge_defaults(
        spaces=["bound-a", "bound-b"],
        scenario="policy-review",
    )
    try:
        assert resolve_agent_knowledge_scope(None, None) == (
            ["bound-a", "bound-b"],
            "policy-review",
        )
        assert resolve_agent_knowledge_scope(
            ["bound-b", "outside"],
            "general-qa",
        ) == (["bound-b"], "policy-review")
    finally:
        reset_agent_knowledge_defaults(token)


def test_knowledge_scope_without_agent_keeps_request():
    from deerflow.knowledge.service import resolve_agent_knowledge_scope

    assert resolve_agent_knowledge_scope(["requested"], "general-qa") == (
        ["requested"],
        "general-qa",
    )


def test_list_configured_kinds_returns_ids():
    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeKindConfig,
        KnowledgeScenarioConfig,
        ScenarioLaneConfig,
        get_knowledge_config,
        set_knowledge_config,
    )
    from deerflow.knowledge.service import list_configured_kinds

    prev = get_knowledge_config()
    try:
        set_knowledge_config(
            KnowledgeConfig(
                kinds=[],
                scenarios=[
                    KnowledgeScenarioConfig(
                        type="policy-review",
                        lanes=[
                            ScenarioLaneConfig(kinds=["policy"]),
                            ScenarioLaneConfig(kinds=["case"]),
                        ],
                    )
                ],
            )
        )
        items = list_configured_kinds()
        assert {k.id for k in items} == {"policy", "case"}

        set_knowledge_config(KnowledgeConfig(kinds=[KnowledgeKindConfig(id="custom-only")], scenarios=[]))
        assert [k.id for k in list_configured_kinds()] == ["custom-only"]
    finally:
        set_knowledge_config(prev)


def test_ensure_kind_allowed_respects_space_whitelist():
    from fastapi import HTTPException

    from deerflow.config.knowledge_config import KnowledgeConfig, get_knowledge_config, set_knowledge_config
    from deerflow.knowledge.service import ensure_kind_allowed

    prev = get_knowledge_config()
    try:
        set_knowledge_config(KnowledgeConfig(kinds=[], scenarios=[]))
        assert ensure_kind_allowed(kind="any-custom", space_allowed_kinds=[]) == "any-custom"
        with pytest.raises(HTTPException) as exc:
            ensure_kind_allowed(kind="other", space_allowed_kinds=["policy"])
        assert exc.value.status_code == 422
    finally:
        set_knowledge_config(prev)


def test_kinds_api_lists_catalog():
    client = TestClient(_api_app())
    res = client.get(
        "/api/knowledge/v1/kinds",
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code in (200, 401, 403)
    if res.status_code == 200:
        body = res.json()
        assert isinstance(body.get("items"), list)
        assert body["total"] == len(body["items"])


class TestKnowledgeLanes:
    """Scenario lane resolve + slot/RRF merge (orchestration only; retrieval uses LlamaIndex)."""

    def test_resolve_lanes_from_config(self):
        from deerflow.config.knowledge_config import KnowledgeScenarioConfig, ScenarioLaneConfig
        from deerflow.knowledge.rag import resolve_lanes

        scenario = KnowledgeScenarioConfig(
            type="policy-review",
            top_k=10,
            lanes=[
                ScenarioLaneConfig(kinds=["policy"], tags=["statute"], budget=4),
                ScenarioLaneConfig(kinds=["case"]),
            ],
        )
        lanes = resolve_lanes(scenario, top_k=10)
        assert lanes[0].budget == 4
        assert lanes[1].budget == 10
        assert lanes[0].tags == ["statute"]

    def test_scenario_kind_ids_from_lanes(self):
        from deerflow.config.knowledge_config import KnowledgeScenarioConfig, ScenarioLaneConfig
        from deerflow.knowledge.rag import scenario_kind_ids

        scenario = KnowledgeScenarioConfig(
            type="policy-review",
            lanes=[
                ScenarioLaneConfig(kinds=["policy"], tags=["statute"]),
                ScenarioLaneConfig(kinds=["policy"], tags=["company-policy"]),
                ScenarioLaneConfig(kinds=["reference"]),
                ScenarioLaneConfig(kinds=["case"]),
            ],
        )
        assert scenario_kind_ids(scenario) == ["policy", "reference", "case"]
        assert scenario_kind_ids(KnowledgeScenarioConfig(type="general-qa")) == []

    def test_merge_slot_then_rrf_keeps_weak_lane(self):
        from deerflow.knowledge.rag import merge_lane_hits

        buckets = [
            ("statute", [{"id": "law-1", "score": 0.95}], 4),
            ("company", [{"id": "co-1", "score": 0.94}], 3),
            ("reference", [{"id": "ref-1", "score": 0.93}], 2),
            ("case", [{"id": "case-1", "score": 0.40}], 3),
        ]
        merged = merge_lane_hits(buckets, final_top_k=4, merge_mode="slot_then_rrf")
        assert {x["id"] for x in merged} == {"law-1", "co-1", "ref-1", "case-1"}

    def test_evaluate_search_cases_needle_hit(self):
        from unittest.mock import patch

        from deerflow.knowledge.rag import evaluate_search_cases

        with patch(
            "deerflow.knowledge.rag.search_space",
            return_value=[{"snippet": "合规要求说明", "metadata": {"doc_id": "d1", "release": "current"}}],
        ):
            result = evaluate_search_cases(
                space_ids=["legal"],
                cases=[{"q": "合规要求", "needles": ["合规"]}],
                top_k=5,
            )
        assert result["needle_hit_rate"] >= 1.0
