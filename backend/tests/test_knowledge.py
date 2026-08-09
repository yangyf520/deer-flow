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
from deerflow.knowledge.adapters.storage import (
    _chunk_text_from_pg_row,
    _chunk_text_from_store_metadata,
    _delete_pgvector_rows_for_doc,
    _pg_params_from_vector_config,
    _pg_row_metadata,
    ensure_llama_settings,
    get_embed_model,
    list_document_chunks,
)
from deerflow.knowledge.app.documents import (
    delete_all_documents,
    delete_space,
    import_document,
    list_documents,
)
from deerflow.knowledge.app.query import attach_user_attrs, compute_precision_recall_at_k, eval_recall, search
from deerflow.knowledge.app.spaces import ensure_kind_allowed, resolve_space_role, role_at_least, upsert_grant
from deerflow.knowledge.contract import EvidenceItem, EvidencePackResponse, RecallEvalCase, parse_embed_segments_json
from deerflow.knowledge.engine.chunk import ContextualTitleTransform, build_node_parser
from deerflow.knowledge.engine.evidence import (
    annotate_block_type,
    custom_metadata_from_chunk,
    format_evidence_snippet,
    merge_custom_metadata,
    user_attrs_from_metadata,
)
from deerflow.knowledge.engine.search import (
    apply_rerank,
    apply_score_cutoff,
    build_hybrid_retriever,
    merge_items_by_doc_buckets,
    merge_space_hits,
    metadata_retrieval_allowed,
    rank_by_temporal,
    resolve_scenario,
    retrieve_across_spaces,
    retrieve_in_space,
    space_budgets,
)
from deerflow.utils.file_conversion import sanitize_media


def test_metadata_retrieval_allowed_respects_enabled_and_expiry():
    from datetime import UTC, datetime

    as_of = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    assert metadata_retrieval_allowed({"enabled": False}, as_of) is False
    assert metadata_retrieval_allowed({"enabled": "false"}, as_of) is False
    assert metadata_retrieval_allowed({"enabled": True}, as_of) is True
    expired = {
        "enabled": True,
        "effective_to": "2026-08-01T00:00:00+00:00",
    }
    assert metadata_retrieval_allowed(expired, as_of) is False


def test_rank_by_temporal_filters_disabled_documents():
    from datetime import UTC, datetime

    items = [
        {"id": "a", "score": 1.0, "metadata": {"enabled": True}},
        {"id": "b", "score": 0.9, "metadata": {"enabled": False}},
    ]
    ranked = rank_by_temporal(items, query="", as_of=datetime(2026, 8, 8, tzinfo=UTC))
    assert [item["id"] for item in ranked] == ["a"]


def test_filter_hits_by_document_state_uses_live_document_row():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from deerflow.knowledge.engine.search import filter_hits_by_document_state

    as_of = datetime(2026, 8, 8, tzinfo=UTC)
    row = SimpleNamespace(
        attrs={"enabled": False},
        effective_from=None,
        effective_to=None,
    )
    hits = [
        {"id": "chunk-1", "score": 0.9, "metadata": {"doc_id": "doc-a", "enabled": True}},
        {"id": "chunk-2", "score": 0.8, "metadata": {"doc_id": "doc-b", "enabled": True}},
    ]
    filtered = filter_hits_by_document_state(hits, {"doc-a": row}, as_of=as_of)
    assert [hit["id"] for hit in filtered] == ["chunk-2"]


def test_pg_params_prefer_connection_string():
    from deerflow.config.knowledge_config import KnowledgeVectorStoreConfig

    cfg = KnowledgeVectorStoreConfig(
        type="pgvector",
        connection_string="postgresql://u:secret@db.example:6543/kb",
        host="ignored",
        database="ignored",
    )
    params = _pg_params_from_vector_config(cfg)
    assert params["host"] == "db.example"
    assert params["port"] == 6543
    assert params["database"] == "kb"
    assert params["user"] == "u"
    assert params["password"] == "secret"


def test_pg_params_use_discrete_fields_when_no_url():
    from deerflow.config.knowledge_config import KnowledgeVectorStoreConfig

    cfg = KnowledgeVectorStoreConfig(
        type="pgvector",
        host="127.0.0.1",
        port=5433,
        database="vectors",
        user="kb",
        password="pw",
    )
    params = _pg_params_from_vector_config(cfg)
    assert params == {
        "host": "127.0.0.1",
        "port": 5433,
        "database": "vectors",
        "user": "kb",
        "password": "pw",
    }


def test_chunk_text_from_store_metadata():
    assert _chunk_text_from_store_metadata({"text": "beef chunk"}) == "beef chunk"
    assert _chunk_text_from_store_metadata({"_node_content": '{"text":"serialized chunk"}'}) == "serialized chunk"


def test_chunk_text_from_pg_row_prefers_text_column():
    row = SimpleNamespace(text="牛肉分块", metadata_={"doc_id": "d1"})
    assert _chunk_text_from_pg_row(row, _pg_row_metadata(row)) == "牛肉分块"


def test_list_document_chunks_pgvector_fallback():
    with (
        patch("deerflow.knowledge.adapters.storage.load_docstore") as load_ds,
        patch("deerflow.knowledge.adapters.storage._list_document_chunks_from_pgvector") as pg,
    ):
        load_ds.return_value = SimpleNamespace(docs={})
        pg.return_value = [
            {
                "id": "c1",
                "index": 1,
                "text": "beef",
                "char_count": 4,
                "block": "text",
                "heading_path": None,
                "page": None,
                "parse_quality": None,
            }
        ]
        items = list_document_chunks(space_id="space-1", doc_id="doc-1")
        pg.assert_called_once_with(space_id="space-1", doc_id="doc-1")
        assert items[0]["text"] == "beef"


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
        "deerflow.knowledge.app.documents.resolve_user_display_names",
        new=AsyncMock(return_value={"u1": "u1"}),
    ):
        items, total = await list_documents(session, "legal", kind="policy", limit=20, offset=0)

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
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    out = await upsert_grant(
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
    session = AsyncMock()
    rows = []
    page = MagicMock()
    page.scalars.return_value.all.return_value = rows
    session.scalar = AsyncMock(return_value=0)
    session.execute = AsyncMock(return_value=page)

    with patch(
        "deerflow.knowledge.app.documents.resolve_user_display_names",
        new=AsyncMock(return_value={}),
    ):
        items, total = await list_documents(session, "legal", q="handbook", limit=20, offset=0)

    assert total == 0
    assert items == []
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_import_dedupes_same_checksum():
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
        patch("deerflow.knowledge.app.documents.hashlib.sha256") as sha,
        patch("deerflow.knowledge.app.documents.asyncio.create_task") as create_task,
    ):
        sha.return_value.hexdigest.return_value = "deadbeef"
        out = await import_document(
            factory,
            space_id="legal",
            user_id="u1",
            filename="a.docx",
            content_type="application/octet-stream",
            data=b"abc",
            kind="policy",
            attrs={"ingest_mode": "structured"},
        )
        assert out.doc_id == "doc-old"
        assert out.deduped is True
        assert existing.attrs == {"ingest_mode": "structured"}
        create_task.assert_not_called()


def test_knowledge_fk_ondelete_cascade():
    from deerflow.persistence.knowledge.model import KnowledgeDocumentRow, KnowledgeGrantRow

    doc_fk = next(c for c in KnowledgeDocumentRow.__table__.constraints if c.name == "fk_knowledge_documents_space_id")
    grant_fk = next(c for c in KnowledgeGrantRow.__table__.constraints if c.name == "fk_knowledge_grants_space_id")
    assert doc_fk.ondelete == "CASCADE"
    assert grant_fk.ondelete == "CASCADE"


@pytest.mark.asyncio
async def test_delete_space_clears_vectors_then_db():
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
        patch("deerflow.knowledge.app.spaces.resolve_space_role", new=AsyncMock(return_value="admin")),
        patch("deerflow.knowledge.app.documents.asyncio.to_thread", side_effect=_to_thread),
        patch("deerflow.knowledge.app.documents.delete_document_vectors") as del_doc,
        patch("deerflow.knowledge.app.documents.delete_space_vectors") as del_vec,
    ):
        del_doc.return_value = 1
        del_vec.return_value = 3
        await delete_space(session, space_id="legal", user_id="u1", system_role="user")
        del_doc.assert_called_once_with(space_id="legal", doc_id="d1")
        del_vec.assert_called_once_with(space_id="legal")
        session.delete.assert_called_once_with(space)


@pytest.mark.asyncio
async def test_delete_all_documents_clears_vectors_then_db():
    doc_a = SimpleNamespace(id="d1", space_id="legal")
    doc_b = SimpleNamespace(id="d2", space_id="legal")
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [doc_a, doc_b]
    session.execute = AsyncMock(return_value=result)
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    async def _to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with (
        patch("deerflow.knowledge.app.documents.asyncio.to_thread", side_effect=_to_thread),
        patch("deerflow.knowledge.app.documents.delete_document_vectors") as del_doc,
    ):
        del_doc.return_value = 1
        deleted = await delete_all_documents(
            session,
            space_id="legal",
        )
        assert deleted == 2
        assert del_doc.call_count == 2
        assert session.delete.call_count == 2
        session.commit.assert_called_once()


def test_delete_pgvector_predicate_covers_doc_id_fields():
    """Ensure delete helper targets ref_doc_id and metadata.doc_id (not only node list)."""
    import inspect

    src = inspect.getsource(_delete_pgvector_rows_for_doc)
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
            out = apply_rerank([SimpleNamespace(score=0.1)], query="E4", top_n=2)
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
            get_embed_model()
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
            assert ensure_llama_settings() is True
        fake_cls.assert_called_once()
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["api_base"] == "https://example.com/v1"
        assert mock_settings.llm is not None
    finally:
        set_knowledge_config(prev)


def test_knowledge_extra_does_not_require_chromadb():
    from deerflow.knowledge.runtime import knowledge_extra_available

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

    prev = get_knowledge_config()
    try:
        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="auto")))
        # Plain prose (no markdown headings) → HierarchicalNodeParser
        parser = build_node_parser([Document(text="hello world without headings")])
        assert isinstance(parser, HierarchicalNodeParser)

        # Markdown headings → MarkdownNodeParser in auto mode
        parser = build_node_parser([Document(text="# hello\n\nworld")])
        assert isinstance(parser, MarkdownNodeParser)

        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="markdown")))
        parser = build_node_parser([Document(text="# hello\n\nworld")])
        assert isinstance(parser, MarkdownNodeParser)

        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="hierarchical")))
        parser = build_node_parser([Document(text="# hello\n\nworld")])
        assert isinstance(parser, HierarchicalNodeParser)
    finally:
        set_knowledge_config(prev)


def test_build_node_parser_ignores_kind():
    from llama_index.core import Document
    from llama_index.core.node_parser import HierarchicalNodeParser, MarkdownNodeParser

    from deerflow.config.knowledge_config import (
        KnowledgeConfig,
        KnowledgeIngestConfig,
        get_knowledge_config,
        set_knowledge_config,
    )

    prev = get_knowledge_config()
    try:
        set_knowledge_config(KnowledgeConfig(ingest=KnowledgeIngestConfig(strategy="auto", chunk_sizes=[1024, 256])))
        plain = [Document(text="Q: 如何报销？\nA: 走财务系统提交票据即可。")]
        faq_parser = build_node_parser(plain)
        policy_parser = build_node_parser([Document(text="第一章 总则。" + ("条款内容。" * 40))])
        assert isinstance(faq_parser, HierarchicalNodeParser)
        assert isinstance(policy_parser, HierarchicalNodeParser)

        md_parser = build_node_parser([Document(text="# hello\n\nworld")])
        assert isinstance(md_parser, MarkdownNodeParser)
    finally:
        set_knowledge_config(prev)


def test_compute_precision_recall_at_k():
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
    raw = "前言\n\ndata:image/jpeg;base64," + ("A" * 200) + "\n\n生物特征数据是指面部图像或指纹。"
    cleaned = sanitize_media(raw)
    assert "base64" not in cleaned
    assert "[image]" in cleaned
    assert annotate_block_type("| a | b |\n| --- | --- |\n| 1 | 2 |") == "table"
    snip = format_evidence_snippet(raw + ("填充。" * 400), "生物特征数据", max_chars=200)
    assert "base64" not in snip
    assert len(snip) <= 220
    assert "生物特征" in snip or "面部" in snip


def test_score_cutoff_filters_low_rerank_scores():
    from types import SimpleNamespace

    nodes = [
        SimpleNamespace(score=0.9, node=SimpleNamespace()),
        SimpleNamespace(score=0.2, node=SimpleNamespace()),
    ]
    kept = apply_score_cutoff(nodes, 0.35)
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
            patch("deerflow.knowledge.engine.search.load_docstore", return_value=docstore),
            patch("deerflow.knowledge.engine.search.get_vector_store", return_value=vector_store),
            patch("deerflow.knowledge.engine.search.get_embed_model", return_value=MagicMock()),
            patch("llama_index.core.StorageContext.from_defaults", return_value=MagicMock()),
            patch("llama_index.core.VectorStoreIndex.from_vector_store", return_value=index),
            patch("llama_index.core.retrievers.QueryFusionRetriever", return_value=fusion),
            patch("llama_index.core.retrievers.AutoMergingRetriever", return_value=amalg) as auto_cls,
            patch("deerflow.knowledge.engine.search.ensure_llama_settings", return_value=False),
        ):
            out = build_hybrid_retriever(space_id="s1", retrieve_n=10, num_queries=1)
        assert out is amalg
        auto_cls.assert_called_once()
    finally:
        set_knowledge_config(prev)


def test_scenario_pack_defaults():
    from deerflow.config.knowledge_config import KnowledgeScenarioConfig

    policy_review = KnowledgeScenarioConfig(type="policy-review", top_k=10, score=0.3)
    with patch("deerflow.knowledge.app.codes.cached_scenario", return_value=policy_review):
        pack = resolve_scenario(request_scenario=None, space_default_scenarios=["policy-review"])
        assert pack.id == "policy-review"
        assert pack.top_k == 10


def test_search_requires_auth():
    client = TestClient(_api_app())
    assert client.post("/api/v1/knowledge/search", json={"query": "hello"}).status_code == 401


@pytest.mark.asyncio
async def test_search_applies_scenario_pack():
    from deerflow.config.knowledge_config import KnowledgeScenarioConfig

    policy_review = KnowledgeScenarioConfig(
        type="policy-review",
        top_k=10,
        score=0.3,
        fusion_num_queries=1,
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
    with (
        patch("deerflow.knowledge.app.codes.cached_scenario", return_value=policy_review),
        patch(
            "deerflow.knowledge.app.query.list_accessible_spaces",
            new=AsyncMock(return_value=[space]),
        ),
        patch("deerflow.knowledge.app.query.retrieve_in_space") as search_one_space,
    ):
        search_one_space.return_value = [
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
        pack = await search(
            AsyncMock(),
            user_id="u1",
            system_role="user",
            query="E4级产品",
            spaces=["legal"],
            top_k=None,
            scenario=None,
        )
        assert len(pack.items) == 1
        assert search_one_space.call_args.kwargs["top_k"] == 10
        assert search_one_space.call_args.kwargs["similarity_cutoff"] == 0.3
        assert search_one_space.call_args.kwargs["fusion_queries"] == 1


@pytest.mark.asyncio
async def test_search_excludes_disabled_document():
    disabled_row = SimpleNamespace(
        id="doc-disabled",
        title="Disabled",
        source_filename=None,
        attrs={"enabled": False},
        effective_from=None,
        effective_to=None,
    )
    space = SimpleNamespace(
        id="legal",
        default_scenarios=[],
        name="legal",
        description=None,
        access="open",
        owner_user_id="u1",
        allowed_kinds=[],
        created_at=None,
        updated_at=None,
        attrs={"top_k": 8, "score": 0.35},
    )
    hit = {
        "id": "n1",
        "source": "chunk",
        "kind": "general",
        "title": "Disabled",
        "snippet": "should not surface",
        "score": 0.99,
        "citable_as": "Disabled",
        "metadata": {"doc_id": "doc-disabled", "space_id": "legal", "enabled": True},
    }
    result = MagicMock()
    result.scalars.return_value.all.return_value = [disabled_row]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    with (
        patch(
            "deerflow.knowledge.app.query.list_accessible_spaces",
            new=AsyncMock(return_value=[space]),
        ),
        patch(
            "deerflow.knowledge.app.query.retrieve_in_space",
            return_value=[hit],
        ),
    ):
        pack = await search(
            session,
            user_id="u1",
            system_role="user",
            query="license-ca",
            spaces=["legal"],
            top_k=5,
        )

    assert pack.items == []


@pytest.mark.asyncio
async def test_search_merges_parallel_spaces():
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
                    top_k=4,
                    score=0.3,
                    merge_mode="slot_then_rrf",
                )
            ]
        )
    )
    spaces = [
        SimpleNamespace(id="legal", default_scenarios=["policy-review"]),
        SimpleNamespace(id="company", default_scenarios=["policy-review"]),
    ]

    def _fake_space(*, space_id, **kwargs):
        return [
            {
                "id": f"{space_id}-1",
                "source": "chunk",
                "kind": "policy",
                "title": space_id,
                "snippet": "s",
                "score": 0.9,
                "metadata": {"space_id": space_id},
            }
        ]

    try:
        with (
            patch(
                "deerflow.knowledge.app.query.list_accessible_spaces",
                new=AsyncMock(return_value=spaces),
            ),
            patch("deerflow.knowledge.app.query.retrieve_in_space", side_effect=_fake_space),
        ):
            pack = await search(
                AsyncMock(),
                user_id="u1",
                system_role="user",
                query="clause",
                spaces=["legal", "company"],
                top_k=None,
                scenario="policy-review",
            )
        assert {it.id for it in pack.items} == {"legal-1", "company-1"}
        assert pack.metadata.get("merge_mode") == "slot_then_rrf"
        assert len(pack.metadata.get("spaces") or []) == 2
        assert len(pack.metadata.get("space_results") or []) == 2
    finally:
        set_knowledge_config(prev)


@pytest.mark.asyncio
async def test_search_empty_spaces_returns_no_hits():
    space = SimpleNamespace(id="legal", default_scenarios=["policy-review"])
    with (
        patch(
            "deerflow.knowledge.app.query.list_accessible_spaces",
            new=AsyncMock(return_value=[space]),
        ),
        patch("deerflow.knowledge.app.query.retrieve_in_space") as search_one_space,
    ):
        pack = await search(
            AsyncMock(),
            user_id="u1",
            system_role="user",
            query="hello",
            spaces=[],
            top_k=None,
            scenario=None,
        )
        assert pack.items == []
        search_one_space.assert_not_called()


def test_set_agent_knowledge_defaults_empty_spaces():
    from deerflow.knowledge.runtime import (
        get_agent_knowledge_defaults,
        reset_agent_knowledge_defaults,
        set_agent_knowledge_defaults,
    )

    token = set_agent_knowledge_defaults(spaces=[], scenario=None)
    assert get_agent_knowledge_defaults() == {"spaces": []}
    reset_agent_knowledge_defaults(token)


def test_agent_knowledge_scope_is_a_hard_ceiling():
    from deerflow.knowledge.runtime import (
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
    from deerflow.knowledge.runtime import resolve_agent_knowledge_scope

    assert resolve_agent_knowledge_scope(["requested"], "general-qa") == (
        ["requested"],
        "general-qa",
    )


def test_ensure_kind_allowed_respects_space_whitelist():
    from fastapi import HTTPException

    assert ensure_kind_allowed(kind="any-custom", space_allowed_kinds=[]) == "any-custom"
    with pytest.raises(HTTPException) as exc:
        ensure_kind_allowed(kind="other", space_allowed_kinds=["policy"])
    assert exc.value.status_code == 422


def test_kinds_api_lists_catalog():
    client = TestClient(_api_app())
    res = client.get(
        "/api/v1/knowledge/kinds",
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code in (200, 401, 403)
    if res.status_code == 200:
        body = res.json()
        assert isinstance(body.get("items"), list)
        assert body["total"] == len(body["items"])


def test_knowledge_catalog_api():
    client = TestClient(_api_app())
    res = client.get(
        "/api/v1/knowledge/catalog",
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code in (200, 401, 403)
    if res.status_code == 200:
        body = res.json()
        for key in ("kinds", "tags", "tag_groups", "scenarios"):
            assert key in body
            assert isinstance(body[key], list)


class TestKnowledgeSpaceMerge:
    """Per-space parallel retrieval merge (orchestration only)."""

    def test_space_budgets_even_split(self):
        assert space_budgets(2, 10) == [5, 5]
        assert space_budgets(3, 10) == [4, 3, 3]

    def test_merge_slot_then_rrf_keeps_each_space(self):
        buckets = [
            ("legal", [{"id": "law-1", "score": 0.95}], 4),
            ("company", [{"id": "co-1", "score": 0.94}], 3),
            ("reference", [{"id": "ref-1", "score": 0.93}], 2),
            ("case", [{"id": "case-1", "score": 0.40}], 3),
        ]
        merged = merge_space_hits(buckets, final_top_k=4, merge_mode="slot_then_rrf")
        assert {x["id"] for x in merged} == {"law-1", "co-1", "ref-1", "case-1"}

    def test_per_doc_merge_from_pooled_hits(self):
        pooled = [
            {"id": "a1", "score": 0.99, "metadata": {"doc_id": "doc-a"}},
            {"id": "a2", "score": 0.98, "metadata": {"doc_id": "doc-a"}},
            {"id": "b1", "score": 0.50, "metadata": {"doc_id": "doc-b"}},
        ]
        merged = merge_items_by_doc_buckets(pooled, final_top_k=2, merge_mode="slot_then_rrf")
        assert {x["id"] for x in merged} == {"a1", "b1"}

    def test_search_one_space_per_doc_parallel(self):
        from unittest.mock import patch

        def _fake_retrieve(**kwargs):
            doc_id = kwargs.get("doc_id")
            if doc_id == "doc-a":
                return [{"id": "a1", "score": 0.9, "metadata": {"doc_id": "doc-a", "space_id": "legal"}}]
            if doc_id == "doc-b":
                return [{"id": "b1", "score": 0.4, "metadata": {"doc_id": "doc-b", "space_id": "legal"}}]
            return []

        with (
            patch("deerflow.knowledge.engine.search.list_space_doc_ids", return_value=["doc-a", "doc-b"]),
            patch("deerflow.knowledge.engine.search.retrieve_space_items", side_effect=_fake_retrieve),
        ):
            out = retrieve_in_space(space_id="legal", query="q", top_k=2)
        assert {x["id"] for x in out} == {"a1", "b1"}

    @pytest.mark.asyncio
    async def test_eval_recall_needle_hit_uses_search(self):
        pack = EvidencePackResponse(
            knowledge_version="current",
            trace_id="trace-1",
            items=[
                EvidenceItem(
                    id="n1",
                    source="chunk",
                    kind="general",
                    title="t",
                    snippet="合规要求说明",
                    score=0.9,
                    citable_as="t",
                    metadata={"doc_id": "d1", "space_id": "legal"},
                )
            ],
        )
        space = SimpleNamespace(id="legal")
        with (
            patch(
                "deerflow.knowledge.app.query.list_accessible_spaces",
                new=AsyncMock(return_value=[space]),
            ),
            patch("deerflow.knowledge.app.query.search", new=AsyncMock(return_value=pack)) as mock_search,
        ):
            result = await eval_recall(
                AsyncMock(),
                user_id="u1",
                system_role="user",
                spaces=["legal"],
                cases=[RecallEvalCase(q="合规要求", needles=["合规"])],
                top_k=5,
            )
        assert mock_search.await_count == 1
        assert result.needle_hit_rate >= 1.0
        assert result.cases[0]["hits"] == 1


def test_tag_group_applies_only_when_lane_tags_overlap():
    from deerflow.config.knowledge_config import (
        KnowledgeScenarioConfig,
        KnowledgeTagGroupConfig,
        ScenarioLaneConfig,
    )
    from deerflow.knowledge.app.codes import _tag_group_fits

    general = KnowledgeScenarioConfig(type="general-qa", top_k=8, score=0.35)
    policy = KnowledgeScenarioConfig(
        type="policy-review",
        lanes=[
            ScenarioLaneConfig(kinds=["policy"], tags=["statute", "national-law"]),
            ScenarioLaneConfig(kinds=["policy"], tags=["company-policy"]),
        ],
    )
    national = KnowledgeTagGroupConfig(id="national", tags=["statute", "national-law"])
    company = KnowledgeTagGroupConfig(id="company", tags=["company-policy"])

    assert not _tag_group_fits(general, national)
    assert not _tag_group_fits(general, company)
    assert _tag_group_fits(policy, national)
    assert _tag_group_fits(policy, company)


def test_compact_scenario_attrs_drops_redundant_fields():
    from deerflow.knowledge.app.codes import _compact_scenario_attrs, linked_scenario_space_id

    assert linked_scenario_space_id("finance-review", {}) == "finance-review"
    assert linked_scenario_space_id("finance-review", {"space_id": "finance-review"}) == "finance-review"

    compact = _compact_scenario_attrs(
        {
            "description": "",
            "top_k": 8,
            "score": 0.35,
            "merge_mode": "slot_then_rrf",
            "fusion_num_queries": None,
            "kinds": ["policy", "case"],
            "lanes": [{"kinds": ["policy"], "budget": 4}],
            "labels": {"zh-CN": "制度预审"},
            "space_id": "finance-review",
        },
        code="finance-review",
    )
    assert "space_id" not in compact
    assert "kinds" not in compact
    assert "top_k" not in compact
    assert "score" not in compact
    assert "merge_mode" not in compact
    assert "fusion_num_queries" not in compact
    assert "description" not in compact
    assert compact["lanes"] == [{"kinds": ["policy"], "budget": 4}]
    assert compact["labels"] == {"zh-CN": "制度预审"}

    override = _compact_scenario_attrs(
        {"space_id": "legacy-space", "labels": {"zh-CN": "旧库"}},
        code="finance-review",
    )
    assert override["space_id"] == "legacy-space"

    host = _compact_scenario_attrs(
        {"host_space_id": "legal-kb", "labels": {"zh-CN": "法务"}},
        code="finance-review",
    )
    assert host["host_space_id"] == "legal-kb"
    assert "space_id" not in host


def test_custom_metadata_from_chunk_excludes_system_keys():
    meta = {
        "space_id": "s1",
        "doc_id": "d1",
        "row_no": 12,
        "source_table": "orders",
        "_internal": "skip",
    }
    assert custom_metadata_from_chunk(meta) == {"row_no": 12, "source_table": "orders"}


def test_user_attrs_from_metadata_omits_system_keys():
    meta = {
        "space_id": "legal",
        "doc_id": "d1",
        "block": "text",
        "heading_path": "§1",
        "page_no": 3,
        "scenario": "policy-review",
        "row_no": 7,
        "detail_id": "rule-42",
    }
    assert user_attrs_from_metadata(meta) == {"row_no": 7, "detail_id": "rule-42"}
    assert user_attrs_from_metadata({}) == {}


def testattach_user_attrs_sets_field_only_when_present():

    with_attrs = EvidenceItem(
        id="e1",
        source="chunk",
        kind="policy",
        title="t",
        snippet="s",
        metadata={"doc_id": "d1", "row_no": 3},
    )
    without = EvidenceItem(
        id="e2",
        source="chunk",
        kind="policy",
        title="t",
        snippet="s",
        metadata={"doc_id": "d1", "heading_path": "§1"},
    )
    attach_user_attrs([with_attrs, without])
    assert with_attrs.attrs == {"row_no": 3}
    assert without.attrs is None


def test_parse_embed_segments_json():
    segments = parse_embed_segments_json('[{"text":"row one","metadata":{"row_no":1}}, {"text":"row two","metadata":{"row_no":2}}]')
    assert segments is not None
    assert len(segments) == 2
    assert segments[0].metadata["row_no"] == 1


def test_merge_custom_metadata_preserves_system_keys():
    base = {"space_id": "s1", "doc_id": "d1", "kind": "general"}
    merged = merge_custom_metadata(base, {"row_no": 3, "space_id": "evil", "doc_id": "x"})
    assert merged["space_id"] == "s1"
    assert merged["doc_id"] == "d1"
    assert merged["row_no"] == 3


def test_search_space_returns_custom_chunk_metadata():
    node = SimpleNamespace(
        node_id="n1",
        metadata={
            "space_id": "legal",
            "doc_id": "d1",
            "kind": "general",
            "title": "Doc",
            "release": "current",
            "tags": "",
            "row_no": 7,
            "batch_id": "b-1",
        },
        text="snippet text",
        relationships={},
    )
    scored = SimpleNamespace(node=node, score=0.9, get_content=lambda: "snippet text")

    with (
        patch("deerflow.knowledge.engine.search.get_knowledge_config") as cfg,
        patch("deerflow.knowledge.engine.search.build_hybrid_retriever", return_value=SimpleNamespace(retrieve=lambda _q: [scored])),
        patch("deerflow.knowledge.engine.search.apply_score_cutoff", side_effect=lambda nodes, _cutoff: nodes),
        patch("deerflow.knowledge.engine.search.rank_by_temporal", side_effect=lambda items, **_kw: items),
        patch("deerflow.knowledge.engine.search.stable_rank_items", side_effect=lambda items: items),
    ):
        cfg.return_value.retrieval.top_k = 5
        cfg.return_value.retrieval.retrieve_n = 10
        cfg.return_value.retrieval.similarity_cutoff = 0.0
        cfg.return_value.retrieval.snippet_max_chars = 500
        cfg.return_value.retrieval.hybrid = False
        cfg.return_value.retrieval.rerank = False
        items = retrieve_across_spaces(space_ids=["legal"], query="test", final_top_k=5, pool_k=5)
    assert items[0]["metadata"]["row_no"] == 7
    assert items[0]["metadata"]["batch_id"] == "b-1"
