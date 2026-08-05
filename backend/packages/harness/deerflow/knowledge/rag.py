"""Knowledge RAG: Docling parse + LlamaIndex ingest/retrieve (library assembly).

Prefer LlamaIndex / Docling via config ``use:`` paths; this module is glue +
business filters (lanes, temporal), not hand-rolled RAG algorithms.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from deerflow.config.knowledge_config import KnowledgeScenarioConfig, get_knowledge_config
from deerflow.config.runtime_paths import runtime_home
from deerflow.utils.file_conversion import sanitize_media

logger = logging.getLogger(__name__)

# After a QueryFusion LLM failure, skip multi-query for the process lifetime (retry still works).
_fusion_llm_disabled: bool = False

# System chunk metadata keys — not treated as caller-defined custom fields.
RESERVED_CHUNK_METADATA_KEYS = frozenset(
    {
        "space_id",
        "doc_id",
        "kind",
        "sensitivity",
        "release",
        "title",
        "parse_quality",
        "tags",
        "effective_from",
        "effective_to",
        "ref_doc_id",
        "document_id",
        "doc_hash",
        "_node_content",
        "excluded_embed_metadata_keys",
        "excluded_llm_metadata_keys",
    }
)

# Runtime Evidence fields — not caller-defined; omitted from ``attrs`` in JSON responses.
EVIDENCE_SYSTEM_METADATA_KEYS = RESERVED_CHUNK_METADATA_KEYS | frozenset(
    {
        "block",
        "heading_path",
        "parent_id",
        "page_no",
        "asset_uri",
        "scenario",
        "spaces_searched",
        "lane_id",
        "lane_fallback",
        "source_filename",
        "doc_title",
        "article_no",
    }
)


def custom_metadata_from_chunk(meta: dict[str, Any]) -> dict[str, Any]:
    """Return caller-defined fields stored on a vector chunk (excludes system keys)."""
    out: dict[str, Any] = {}
    for key, value in (meta or {}).items():
        if not key or key.startswith("_") or key in RESERVED_CHUNK_METADATA_KEYS:
            continue
        out[key] = value
    return out


def user_attrs_from_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Caller-defined fields on Evidence metadata for JSON responses (omit when empty)."""
    out: dict[str, Any] = {}
    for key, value in (meta or {}).items():
        if not key or key.startswith("_") or key in EVIDENCE_SYSTEM_METADATA_KEYS:
            continue
        out[key] = value
    return out


def merge_custom_metadata(base: dict[str, Any], custom: dict[str, Any] | None) -> dict[str, Any]:
    """Merge document/segment attrs into ingest metadata without overriding system keys."""
    out = dict(base)
    if not custom:
        return out
    for key, value in custom.items():
        if not key or key.startswith("_") or key in RESERVED_CHUNK_METADATA_KEYS:
            continue
        out[key] = value
    return out


def _instantiate(use: str, kwargs: dict[str, Any]) -> Any:
    """Assemble a LlamaIndex (or other) class from ``package.module:Class`` + kwargs."""
    from deerflow.reflection.resolvers import resolve_class

    cls = resolve_class(use)
    clean = {k: v for k, v in kwargs.items() if v is not None and v != ""}
    try:
        return cls(**clean)
    except TypeError:
        if "model" in clean and "model_name" not in clean:
            alt = dict(clean)
            alt["model_name"] = alt.pop("model")
            try:
                return cls(**alt)
            except TypeError:
                pass
        raise


def _bm25_tokenize(text: str) -> list[str]:
    """BM25 tokenizer — swap via retrieval.bm25_tokenizer (jieba | jieba_search | whitespace)."""
    mode = (get_knowledge_config().retrieval.bm25_tokenizer or "jieba").strip().lower()
    if mode in ("whitespace", "default", "split"):
        return [t.lower() for t in (text or "").split() if t.strip()]
    import jieba

    # jieba_search / default jieba: search mode keeps finer tokens for partial matches
    # (e.g. 个人信息 inside 个人敏感信息 queries).
    if mode in ("jieba_search", "search", "jieba"):
        return [t.lower() for t in jieba.lcut_for_search(text or "") if t.strip()]
    return [t.lower() for t in jieba.lcut(text or "") if t.strip()]


def _node_text(node: Any) -> str:
    if hasattr(node, "get_content"):
        return str(node.get_content() or "")
    return str(getattr(node, "text", "") or "")


_MD_TABLE_RE = re.compile(r"\|.+\|\s*\n\|[-:\s|]+\|", re.MULTILINE)
_MD_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")


def annotate_block_type(text: str) -> str:
    """Infer Evidence ``block`` from content shape (table / image / text)."""
    t = text or ""
    if "[image]" in t.lower() or "data:image/" in t.lower():
        return "image"
    if _MD_TABLE_RE.search(t) or (t.count("|") >= 4 and "---" in t):
        return "table"
    return "text"


def format_evidence_snippet(text: str, query: str, *, max_chars: int = 1200) -> str:
    """Evidence-friendly excerpt: sanitize media, window around query terms, hard cap."""
    cleaned = sanitize_media(text or "")
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    # Prefer a window centered on the densest query-term hits.
    terms = [t for t in _bm25_tokenize(query) if len(t) >= 2][:12]
    best_i = 0
    if terms:
        lower = cleaned.lower()
        hits: list[int] = []
        for term in terms:
            start = 0
            tl = term.lower()
            while True:
                i = lower.find(tl, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + max(len(tl), 1)
                if len(hits) > 40:
                    break
        if hits:
            # Center on median hit
            hits.sort()
            best_i = hits[len(hits) // 2]

    half = max_chars // 2
    start = max(0, best_i - half)
    end = min(len(cleaned), start + max_chars)
    start = max(0, end - max_chars)
    excerpt = cleaned[start:end].strip()
    # Prefer breaking on paragraph / sentence boundaries when cheap
    if start > 0:
        m = re.search(r"[\n。；;]", excerpt)
        if m and m.start() < 80:
            excerpt = excerpt[m.start() + 1 :].lstrip()
        excerpt = "…" + excerpt
    if end < len(cleaned):
        excerpt = excerpt.rstrip() + "…"
    return excerpt[: max_chars + 2]


# ── store (LlamaIndex VectorStore / embed / docstore) ───────────────────────


# ── store (LlamaIndex VectorStore / embed / docstore) ───────────────────────


def get_embed_model():
    """Assemble embedding from ``knowledge.embed.use`` (YAML ctor kwargs → LlamaIndex class)."""
    cfg = get_knowledge_config().embed
    return _instantiate(cfg.resolved().use, cfg.ctor_kwargs())


def ensure_embed_model() -> bool:
    """Set ``Settings._embed_model`` from YAML without touching the lazy OpenAI default.

    Accessing ``Settings.embed_model`` when unset calls ``resolve_embed_model("default")``
    and raises without ``OPENAI_API_KEY``. Always write via the private field check.
    """
    from llama_index.core import Settings

    if getattr(Settings, "_embed_model", None) is not None:
        return True
    try:
        Settings.embed_model = get_embed_model()
        return True
    except Exception as exc:
        logger.debug("embed_model not set: %s", exc)
        return False


def ensure_llama_settings() -> bool:
    """Wire Settings embed + optional query-fusion LLM from ``retrieval.query_llm``.

    Enable via ``enabled: true``, env ``KNOWLEDGE_ENABLE_QUERY_FUSION=1``, or ``auto`` + api_key.
    Vendor swap is YAML ``use:`` only — same pattern as Agent ``models[].use``.
    """
    global _fusion_llm_disabled
    from llama_index.core import Settings

    ensure_embed_model()

    qcfg = get_knowledge_config().retrieval.query_llm
    env_on = (os.getenv("KNOWLEDGE_ENABLE_QUERY_FUSION") or "").strip().lower() in ("1", "true", "yes", "on")
    kwargs = qcfg.ctor_kwargs()
    if not kwargs.get("api_key"):
        embed = get_knowledge_config().embed.resolved()
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY") or embed.api_key or os.getenv("EMBEDDING_API_KEY") or ""
    auto_on = bool(qcfg.auto) and bool(kwargs.get("api_key"))
    if not (qcfg.enabled or env_on or auto_on):
        return False
    # Do not read Settings.llm — its getter lazy-loads OpenAI when unset.
    if getattr(Settings, "_llm", None) is not None:
        return True
    if not kwargs.get("api_key"):
        return False
    if not kwargs.get("model"):
        kwargs["model"] = os.getenv("KNOWLEDGE_QUERY_LLM") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

    try:
        Settings.llm = _instantiate(qcfg.use or "llama_index.llms.openai:OpenAI", kwargs)
        _fusion_llm_disabled = False
        return True
    except Exception as exc:
        logger.debug("LlamaIndex LLM not configured: %s", exc)
        return False


def vectors_dir() -> Path:
    cfg = get_knowledge_config().vector_store
    if cfg.persist_dir:
        p = Path(cfg.persist_dir)
        return p if p.is_absolute() else runtime_home() / p
    return runtime_home() / "knowledge" / "vectors"


def docstore_dir(space_id: str) -> Path:
    """Persist dir for LlamaIndex SimpleDocumentStore (BM25 / parent / chunks)."""
    return vectors_dir() / f"docstore_{space_id}"


def rename_space_vectors(*, old_id: str, new_id: str) -> None:
    """Best-effort rename of on-disk docstore for a knowledge space."""
    import shutil

    old_path = docstore_dir(old_id)
    new_path = docstore_dir(new_id)
    if not old_path.exists():
        return
    new_path.parent.mkdir(parents=True, exist_ok=True)
    if new_path.exists():
        shutil.rmtree(new_path)
    old_path.rename(new_path)
    logger.info("Renamed knowledge docstore %s -> %s", old_id, new_id)


def _database_url() -> str:
    raw = os.getenv("DATABASE_URL") or ""
    if raw:
        return raw
    for candidate in (Path.cwd() / ".env", Path.cwd().parent / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, val = s.split("=", 1)
            if key.strip() == "DATABASE_URL":
                return val.strip().strip('"').strip("'")
    return ""


def _parse_pg_url(raw: str) -> dict:
    """Parse a postgres URL into host/port/database/user/password."""
    from sqlalchemy.engine.url import make_url

    if not raw:
        return {}
    normalized = raw.replace("postgres://", "postgresql://", 1)
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if normalized.startswith(prefix):
            normalized = "postgresql://" + normalized[len(prefix) :]
            break
    u = make_url(normalized)
    return {
        "host": u.host or "localhost",
        "port": int(u.port or 5432),
        "database": u.database or "deerflow",
        "user": u.username or "",
        "password": u.password or "",
    }


def _pg_params_from_database_url() -> dict:
    """Parse DATABASE_URL with SQLAlchemy make_url (same stack as persistence)."""
    return _parse_pg_url(_database_url())


def _pg_params_from_vector_config(cfg) -> dict:
    """Resolve pgvector connection: connection_string → discrete fields → DATABASE_URL."""
    if (cfg.connection_string or "").strip():
        return _parse_pg_url(cfg.connection_string.strip())
    if cfg.host or cfg.database or cfg.user:
        return {
            "host": cfg.host or "localhost",
            "port": int(cfg.port or 5432),
            "database": cfg.database or "deerflow",
            "user": cfg.user or "",
            "password": cfg.password or "",
        }
    return _pg_params_from_database_url()


def _pgvector_store(*, sync_url: str, async_url: str, table_name: str, embed_dim: int):
    """Build PGVectorStore with an exact physical table name (no LlamaIndex ``data_`` prefix)."""
    import llama_index.vector_stores.postgres.base as pg_base
    from llama_index.vector_stores.postgres import PGVectorStore

    table = table_name.replace("-", "_")
    orig = pg_base.get_data_model

    def _exact_table_model(base, index_name: str, *args, **kwargs):
        model = orig(base, index_name, *args, **kwargs)
        # LlamaIndex hardcodes ``data_{table_name}``; force the configured physical name.
        desired = str(index_name or table).replace("-", "_")
        model.__tablename__ = desired
        if getattr(model, "__table__", None) is not None:
            model.__table__.name = desired
            if getattr(model.__table__, "fullname", None) is not None:
                model.__table__.fullname = desired
        return model

    pg_base.get_data_model = _exact_table_model  # type: ignore[assignment]
    try:
        return PGVectorStore.from_params(
            connection_string=sync_url,
            async_connection_string=async_url,
            table_name=table,
            embed_dim=embed_dim,
            use_jsonb=True,
        )
    finally:
        pg_base.get_data_model = orig


def get_vector_store(space_id: str):
    cfg = get_knowledge_config().vector_store
    store_type = (cfg.type or "chroma").lower()
    if store_type in ("postgres", "pgvector"):
        from sqlalchemy.engine.url import URL

        params = _pg_params_from_vector_config(cfg)
        if not params.get("host") and not params.get("database"):
            raise ValueError("knowledge.vector_store: pgvector needs connection_string (or host/database/user/password), or DATABASE_URL")
        host = params.get("host") or "localhost"
        port = int(params.get("port") or 5432)
        database = params.get("database") or "deerflow"
        user = params.get("user") or ""
        password = params.get("password") or ""
        # Pass rendered strings: LlamaIndex does str(URL), which redacts password to "***".
        sync_url = URL.create(
            drivername="postgresql+psycopg2",
            username=user or None,
            password=password or None,
            host=host,
            port=port,
            database=database,
        ).render_as_string(hide_password=False)
        async_url = URL.create(
            drivername="postgresql+asyncpg",
            username=user or None,
            password=password or None,
            host=host,
            port=port,
            database=database,
        ).render_as_string(hide_password=False)
        # Single shared table; isolate by metadata.space_id / metadata.doc_id (not per-space tables).
        table = (cfg.table_name or "knowledge_embed").replace("-", "_")
        return _pgvector_store(
            sync_url=sync_url,
            async_url=async_url,
            table_name=table,
            embed_dim=cfg.embed_dim or get_knowledge_config().embed.embed_dim,
        )
    if store_type == "milvus":
        from llama_index.vector_stores.milvus import MilvusVectorStore

        kwargs: dict = {
            "uri": cfg.uri or "http://localhost:19530",
            "collection_name": f"{cfg.collection_name}_{space_id}".replace("-", "_"),
            "dim": cfg.embed_dim or get_knowledge_config().embed.embed_dim,
            "overwrite": False,
        }
        if (cfg.token or "").strip():
            kwargs["token"] = cfg.token.strip()
        return MilvusVectorStore(**kwargs)
    if store_type not in ("chroma", ""):
        raise ValueError(f"knowledge.vector_store.type={store_type!r} unsupported; use chroma | pgvector | milvus")
    try:
        import chromadb
        from llama_index.vector_stores.chroma import ChromaVectorStore
    except ImportError as exc:
        raise ImportError("Chroma vector store requires chromadb. Install it or set knowledge.vector_store.type to pgvector/milvus.") from exc

    persist = vectors_dir()
    persist.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist))
    collection = client.get_or_create_collection(f"knowledge_{space_id}")
    return ChromaVectorStore(chroma_collection=collection)


def load_docstore(space_id: str):
    from llama_index.core.storage.docstore import SimpleDocumentStore

    path = docstore_dir(space_id)
    try:
        if path.is_dir():
            return SimpleDocumentStore.from_persist_dir(str(path))
        if path.with_suffix(".json").is_file():
            return SimpleDocumentStore.from_persist_path(str(path.with_suffix(".json")))
    except Exception as exc:
        logger.warning("Failed to load docstore %s: %s", path, exc)
    return SimpleDocumentStore()


def persist_docstore(space_id: str, docstore) -> None:
    path = docstore_dir(space_id)
    path.mkdir(parents=True, exist_ok=True)
    docstore.persist(persist_path=str(path / "docstore.json"))


def patch_document_metadata(
    *,
    space_id: str,
    doc_id: str,
    patch: dict[str, Any],
) -> int:
    """Sync metadata fields onto all docstore nodes for a document."""
    docstore = load_docstore(space_id)
    updated = 0
    for node in list(getattr(docstore, "docs", {}).values()):
        meta = dict(getattr(node, "metadata", None) or {})
        if str(meta.get("doc_id") or "") != doc_id:
            continue
        meta.update(patch)
        node.metadata = meta
        updated += 1
    if updated:
        persist_docstore(space_id, docstore)
    return updated


def _patch_pgvector_metadata_for_doc(vector_store: Any, *, doc_id: str, patch: dict[str, Any]) -> int:
    """Merge ``patch`` into pgvector JSON metadata for all rows of a knowledge document."""
    if not patch:
        return 0
    try:
        from sqlalchemy import select
    except ImportError:
        return 0
    if not hasattr(vector_store, "_initialize"):
        return 0
    vector_store._initialize()
    if not hasattr(vector_store, "_session"):
        return 0
    table = getattr(vector_store, "_table_class", None)
    if table is None:
        return 0
    updated = 0
    with vector_store._session() as session, session.begin():
        rows = session.execute(select(table).where(_pgvector_doc_id_filter(table, doc_id))).scalars().all()
        for row in rows:
            meta = _pg_row_metadata(row)
            meta.update(patch)
            if hasattr(row, "metadata_"):
                row.metadata_ = meta
            elif hasattr(row, "metadata"):
                row.metadata = meta
            updated += 1
    return updated


def sync_document_metadata(
    *,
    space_id: str,
    doc_id: str,
    patch: dict[str, Any],
) -> int:
    """Sync metadata onto docstore nodes and pgvector rows for a document."""
    if not patch:
        return 0
    updated = patch_document_metadata(space_id=space_id, doc_id=doc_id, patch=patch)
    try:
        vector_store = get_vector_store(space_id)
        if type(vector_store).__name__ == "PGVectorStore":
            updated = max(updated, _patch_pgvector_metadata_for_doc(vector_store, doc_id=doc_id, patch=patch))
    except Exception as exc:
        logger.warning("pgvector metadata patch failed space=%s doc=%s: %s", space_id, doc_id, exc)
    return updated


def _release_matches(meta: dict[str, Any], want: str) -> bool:
    have = str(meta.get("release") or "current").strip() or "current"
    want_v = (want or "current").strip() or "current"
    return have == want_v


def _chunk_sort_key(meta: dict[str, Any], *, node_id: str = "") -> tuple:
    start = meta.get("start_char_idx")
    try:
        start_i = int(start) if start is not None else 10**12
    except (TypeError, ValueError):
        start_i = 10**12
    page = meta.get("page") or meta.get("page_label")
    try:
        page_i = int(page) if page is not None else 10**9
    except (TypeError, ValueError):
        page_i = 10**9
    return (page_i, start_i, node_id)


def _chunk_items_from_nodes(ordered: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for i, node in enumerate(ordered, start=1):
        meta = dict(getattr(node, "metadata", None) or {})
        text = _node_text(node).strip()
        items.append(
            {
                "id": str(getattr(node, "node_id", None) or getattr(node, "id_", None) or f"chunk-{i}"),
                "index": i,
                "text": text,
                "char_count": len(text),
                "block": meta.get("block") or annotate_block_type(text),
                "heading_path": meta.get("heading_path") or meta.get("section") or None,
                "page": meta.get("page") or meta.get("page_label") or None,
                "parse_quality": meta.get("parse_quality"),
            }
        )
    return items


def _chunk_text_from_store_metadata(meta: dict[str, Any]) -> str:
    raw = meta.get("text") or meta.get("document_text")
    if raw:
        return str(raw).strip()
    node_content = meta.get("_node_content")
    if not node_content:
        return ""
    try:
        payload = json.loads(node_content) if isinstance(node_content, str) else node_content
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    text = payload.get("text") or payload.get("content")
    if text:
        return str(text).strip()
    nested = payload.get("metadata")
    if isinstance(nested, dict) and nested.get("text"):
        return str(nested["text"]).strip()
    return ""


def _pg_row_metadata(row: Any) -> dict[str, Any]:
    raw = getattr(row, "metadata_", None) or getattr(row, "metadata", None) or {}
    return dict(raw or {})


def _chunk_text_from_pg_row(row: Any, meta: dict[str, Any]) -> str:
    text = str(getattr(row, "text", None) or "").strip()
    if text:
        return text
    return _chunk_text_from_store_metadata(meta)


def _pgvector_doc_id_filter(table: Any, doc_id: str) -> Any:
    from sqlalchemy import or_

    return or_(
        table.metadata_["ref_doc_id"].astext == doc_id,
        table.metadata_["doc_id"].astext == doc_id,
        table.metadata_["document_id"].astext == doc_id,
        table.metadata_["_node_content"].astext.contains(f'"doc_id": "{doc_id}"'),
    )


def _list_document_chunks_from_pgvector(*, space_id: str, doc_id: str) -> list[dict[str, Any]]:
    """Fallback when local docstore is empty but pgvector rows exist (common after redeploy)."""
    try:
        from sqlalchemy import select
    except ImportError:
        return []
    try:
        vector_store = get_vector_store(space_id)
    except Exception as exc:
        logger.debug("vector store unavailable for chunk list doc=%s: %s", doc_id, exc)
        return []
    if type(vector_store).__name__ != "PGVectorStore":
        return []
    if not hasattr(vector_store, "_initialize"):
        return []
    vector_store._initialize()
    if not hasattr(vector_store, "_session"):
        logger.warning("pgvector chunk fallback doc=%s: store has no _session after init", doc_id)
        return []
    table = getattr(vector_store, "_table_class", None)
    if table is None:
        return []

    with vector_store._session() as session:
        rows = list(session.scalars(select(table).where(_pgvector_doc_id_filter(table, doc_id))).all())

    if rows:
        logger.debug("pgvector chunk fallback doc=%s rows=%s", doc_id, len(rows))

    candidates: list[tuple[str, dict[str, Any], str]] = []
    for row in rows:
        meta = _pg_row_metadata(row)
        text = _chunk_text_from_pg_row(row, meta)
        if not text:
            continue
        node_id = str(getattr(row, "node_id", None) or getattr(row, "id", None) or meta.get("node_id") or meta.get("id") or "")
        candidates.append((node_id, meta, text))

    if rows and not candidates:
        logger.warning(
            "pgvector chunk fallback doc=%s: %s rows but no extractable text (check text column)",
            doc_id,
            len(rows),
        )

    candidates.sort(key=lambda item: _chunk_sort_key(item[1], node_id=item[0]))

    items: list[dict[str, Any]] = []
    for i, (node_id, meta, text) in enumerate(candidates, start=1):
        items.append(
            {
                "id": node_id or f"chunk-{i}",
                "index": i,
                "text": text,
                "char_count": len(text),
                "block": meta.get("block") or annotate_block_type(text),
                "heading_path": meta.get("heading_path") or meta.get("section") or None,
                "page": meta.get("page") or meta.get("page_label") or None,
                "parse_quality": meta.get("parse_quality"),
            }
        )
    return items


def list_document_chunks(*, space_id: str, doc_id: str) -> list[dict[str, Any]]:
    """List ingest leaf chunks (docstore first, pgvector fallback)."""
    from llama_index.core.node_parser import get_leaf_nodes

    docstore = load_docstore(space_id)
    candidates: list[Any] = []
    for node in list(getattr(docstore, "docs", {}).values()):
        meta = dict(getattr(node, "metadata", None) or {})
        if meta.get("doc_id") != doc_id:
            continue
        candidates.append(node)
    if not candidates:
        return _list_document_chunks_from_pgvector(space_id=space_id, doc_id=doc_id)

    try:
        leaves = list(get_leaf_nodes(candidates) or []) or candidates
    except Exception:
        leaves = candidates

    # Deduplicate by node_id while preserving order
    seen: set[str] = set()
    ordered: list[Any] = []
    for node in leaves:
        nid = str(getattr(node, "node_id", None) or getattr(node, "id_", None) or id(node))
        if nid in seen:
            continue
        seen.add(nid)
        ordered.append(node)

    ordered.sort(
        key=lambda node: _chunk_sort_key(
            _node_chunk_meta(node),
            node_id=str(getattr(node, "node_id", None) or getattr(node, "id_", None) or ""),
        )
    )
    items = _chunk_items_from_nodes(ordered)
    if any(str(item.get("text") or "").strip() for item in items):
        return items
    return _list_document_chunks_from_pgvector(space_id=space_id, doc_id=doc_id)


def _node_chunk_meta(node: Any) -> dict[str, Any]:
    meta = dict(getattr(node, "metadata", None) or {})
    if meta.get("start_char_idx") is None and getattr(node, "start_char_idx", None) is not None:
        meta["start_char_idx"] = getattr(node, "start_char_idx")
    return meta


def _delete_pgvector_rows_for_doc(vector_store, *, doc_id: str) -> int:
    """Delete pgvector rows tied to a knowledge doc_id (ref_doc_id or metadata.doc_id)."""
    try:
        from sqlalchemy import delete, or_
    except ImportError:
        return 0
    if not hasattr(vector_store, "_initialize"):
        return 0
    vector_store._initialize()
    if not hasattr(vector_store, "_session"):
        return 0
    table = getattr(vector_store, "_table_class", None)
    if table is None:
        return 0
    with vector_store._session() as session, session.begin():
        stmt = delete(table).where(
            or_(
                table.metadata_["ref_doc_id"].astext == doc_id,
                table.metadata_["doc_id"].astext == doc_id,
                table.metadata_["document_id"].astext == doc_id,
                # Legacy rows: knowledge doc_id only inside stringified _node_content
                table.metadata_["_node_content"].astext.contains(f'"doc_id": "{doc_id}"'),
            )
        )
        result = session.execute(stmt)
        return int(result.rowcount or 0)


def delete_document_vectors(*, space_id: str, doc_id: str) -> int:
    """Remove vectors + docstore nodes for a knowledge document.

    Knowledge ``doc_id`` must equal LlamaIndex ``ref_doc_id`` (set at ingest via Document.id_).
    Best-effort: vector backend failures are logged and do not raise — callers can still
    remove the document DB row (e.g. when ingest never wrote embeddings).
    """
    removed = 0
    try:
        docstore = load_docstore(space_id)
        to_delete = [nid for nid, node in docstore.docs.items() if (getattr(node, "metadata", None) or {}).get("doc_id") == doc_id]
        for nid in to_delete:
            try:
                docstore.delete_document(nid)
            except Exception:
                pass
        persist_docstore(space_id, docstore)
    except Exception as exc:
        logger.warning("docstore cleanup failed space=%s doc=%s: %s", space_id, doc_id, exc)
        to_delete = []

    try:
        vector_store = get_vector_store(space_id)
    except Exception as exc:
        logger.warning("vector store unavailable for delete space=%s doc=%s: %s", space_id, doc_id, exc)
        return removed

    # pgvector: delete by ref_doc_id / metadata.doc_id in one shot (covers legacy mismatch)
    if type(vector_store).__name__ == "PGVectorStore":
        try:
            removed = _delete_pgvector_rows_for_doc(vector_store, doc_id=doc_id)
        except Exception as exc:
            logger.warning("pgvector metadata delete failed doc=%s: %s", doc_id, exc)

    # Chroma / Milvus / generic: LlamaIndex delete(ref_doc_id=)
    if hasattr(vector_store, "delete") and doc_id:
        try:
            vector_store.delete(ref_doc_id=doc_id)
        except TypeError:
            pass
        except Exception as exc:
            logger.debug("vector_store.delete(ref_doc_id=) skipped: %s", exc)

    if to_delete and hasattr(vector_store, "delete_nodes"):
        try:
            vector_store.delete_nodes(to_delete)
            removed = max(removed, len(to_delete))
        except Exception as exc:
            logger.debug("vector_store.delete_nodes skipped: %s", exc)
    elif to_delete:
        for nid in to_delete:
            try:
                if hasattr(vector_store, "delete"):
                    vector_store.delete(nid)
            except Exception as exc:
                logger.debug("vector delete %s: %s", nid, exc)
        removed = max(removed, len(to_delete))

    logger.info("Deleted vectors space=%s doc=%s docstore_nodes=%s pg_rows=%s", space_id, doc_id, len(to_delete), removed)
    return max(removed, len(to_delete))


def _delete_pgvector_rows_for_space(vector_store, *, space_id: str) -> int:
    """Delete all pgvector rows for a knowledge space_id."""
    try:
        from sqlalchemy import String, cast, delete, or_
    except ImportError:
        return 0
    if not hasattr(vector_store, "_initialize"):
        return 0
    vector_store._initialize()
    if not hasattr(vector_store, "_session"):
        return 0
    table = getattr(vector_store, "_table_class", None)
    if table is None:
        return 0
    with vector_store._session() as session, session.begin():
        stmt = delete(table).where(
            or_(
                table.metadata_["space_id"].astext == space_id,
                table.metadata_["_node_content"].astext.contains(f'"space_id": "{space_id}"'),
                cast(table.metadata_, String).like(f"%{space_id}%"),
            )
        )
        result = session.execute(stmt)
        # begin() context commits on clean exit
        return int(result.rowcount or 0)


def delete_space_vectors(*, space_id: str) -> int:
    """Remove all vectors + docstore for a knowledge space."""
    import shutil

    removed = 0
    path = docstore_dir(space_id)
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.with_suffix(".json").is_file():
            path.with_suffix(".json").unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("docstore remove failed space=%s: %s", space_id, exc)

    cfg = get_knowledge_config().vector_store
    store_type = (cfg.type or "chroma").lower()
    if store_type in ("postgres", "pgvector"):
        try:
            store = get_vector_store(space_id)
            removed = _delete_pgvector_rows_for_space(store, space_id=space_id)
        except Exception as exc:
            logger.warning("pgvector space delete failed space=%s: %s", space_id, exc)
    elif store_type == "milvus":
        try:
            store = get_vector_store(space_id)
            if hasattr(store, "client") and hasattr(store.client, "drop_collection"):
                name = f"{cfg.collection_name}_{space_id}".replace("-", "_")
                store.client.drop_collection(name)
                removed = 1
        except Exception as exc:
            logger.warning("milvus space delete failed space=%s: %s", space_id, exc)
    else:
        try:
            import chromadb

            persist = vectors_dir()
            client = chromadb.PersistentClient(path=str(persist))
            name = f"knowledge_{space_id}"
            try:
                client.delete_collection(name)
                removed = 1
            except Exception:
                pass
        except Exception as exc:
            logger.warning("chroma space delete failed space=%s: %s", space_id, exc)

    logger.info("Deleted space vectors space=%s removed=%s", space_id, removed)
    return removed


# ── ingest (IngestionPipeline) ──────────────────────────────────────────────


def ContextualTitleTransform():
    """Prefix document title before embedding."""
    from llama_index.core.schema import TransformComponent

    class _ContextualTitleTransform(TransformComponent):
        def __call__(self, nodes: Sequence[Any], **kwargs: Any) -> Sequence[Any]:
            for node in nodes:
                meta = dict(getattr(node, "metadata", None) or {})
                title = meta.get("title") or ""
                text = node.get_content() if hasattr(node, "get_content") else getattr(node, "text", "")
                text_s = str(text or "")
                if title and text_s and not text_s.startswith(f"《{title}》"):
                    if hasattr(node, "set_content"):
                        node.set_content(f"《{title}》\n{text_s}")
                    else:
                        node.text = f"《{title}》\n{text_s}"
            return nodes

    return _ContextualTitleTransform()


def MediaSanitizeTransform():
    """LlamaIndex TransformComponent: strip data-URI / base64 media from node text."""
    from llama_index.core.schema import TransformComponent

    class _MediaSanitizeTransform(TransformComponent):
        def __call__(self, nodes: Sequence[Any], **kwargs: Any) -> Sequence[Any]:
            for node in nodes:
                text = _node_text(node)
                cleaned = sanitize_media(text)
                if cleaned != text:
                    if hasattr(node, "set_content"):
                        node.set_content(cleaned)
                    else:
                        node.text = cleaned
            return nodes

    return _MediaSanitizeTransform()


def BlockAnnotateTransform():
    """LlamaIndex TransformComponent: set metadata.block from content shape."""
    from llama_index.core.schema import TransformComponent

    class _BlockAnnotateTransform(TransformComponent):
        def __call__(self, nodes: Sequence[Any], **kwargs: Any) -> Sequence[Any]:
            for node in nodes:
                meta = dict(getattr(node, "metadata", None) or {})
                if not meta.get("block"):
                    meta["block"] = annotate_block_type(_node_text(node))
                    node.metadata = meta
                # Best-effort heading path from first markdown heading in chunk
                if not meta.get("heading_path"):
                    m = _MD_HEADING_RE.search(_node_text(node))
                    if m:
                        line = _node_text(node)[m.start() :].split("\n", 1)[0]
                        heading = re.sub(r"^#{1,6}\s*", "", line).strip()
                        if heading:
                            meta["heading_path"] = heading[:200]
                            node.metadata = meta
            return nodes

    return _BlockAnnotateTransform()


def _looks_like_markdown(docs: Sequence[Any]) -> bool:
    sample = "\n".join((getattr(d, "text", "") or "")[:4000] for d in docs[:3])
    return bool(_MD_HEADING_RE.search(sample) or _MD_TABLE_RE.search(sample))


def _build_node_parser(docs: Sequence[Any], *, kind: str = "general"):
    """Assemble LlamaIndex node parser — format-aware + kind-aware (FAQ whole vs policy hierarchy)."""
    from llama_index.core.node_parser import HierarchicalNodeParser, MarkdownNodeParser, SentenceSplitter

    ingest_cfg = get_knowledge_config().ingest
    strategy = (ingest_cfg.strategy or "auto").strip().lower()
    chunk_sizes = list(ingest_cfg.chunk_sizes or [1024, 256])
    overlap = int(ingest_cfg.chunk_overlap or 64)
    kind_l = (kind or "general").strip().lower()

    # Explicit class path always wins (same pattern as models/tools ``use:``).
    if (ingest_cfg.node_parser_use or "").strip():
        return _instantiate_node_parser(ingest_cfg, chunk_sizes, overlap)

    # FAQ / short cards: keep whole answers — large single-window splitter
    if strategy == "auto" and kind_l in ("faq", "case"):
        size = max(chunk_sizes) if chunk_sizes else 2048
        return SentenceSplitter(chunk_size=size, chunk_overlap=min(overlap, 32))

    # Policy / SOP / reference: prefer hierarchical parent-child when not markdown-headed
    if strategy == "auto" and kind_l in ("policy", "sop", "reference"):
        if _looks_like_markdown(docs):
            return MarkdownNodeParser()
        return HierarchicalNodeParser.from_defaults(chunk_sizes=chunk_sizes, chunk_overlap=overlap)

    # Markdown exports: header-aware sections beat giant hierarchical parents
    if strategy == "markdown" or (strategy == "auto" and _looks_like_markdown(docs)):
        return MarkdownNodeParser()

    if strategy == "hierarchical":
        return HierarchicalNodeParser.from_defaults(chunk_sizes=chunk_sizes, chunk_overlap=overlap)

    # Default / plain text: HierarchicalNodeParser (parent-child)
    return HierarchicalNodeParser.from_defaults(chunk_sizes=chunk_sizes, chunk_overlap=overlap)


def _instantiate_node_parser(ingest_cfg, chunk_sizes: list[int], overlap: int):
    parser_kwargs = {
        k: v
        for k, v in ingest_cfg.model_dump(
            exclude={
                "node_parser_use",
                "chunk_sizes",
                "chunk_overlap",
                "strategy",
                "title_prefix",
                "transforms",
                "media_sanitize",
                "annotate_block",
            }
        ).items()
        if v is not None and v != ""
    }
    parser_kwargs.setdefault("chunk_sizes", chunk_sizes)
    parser_kwargs.setdefault("chunk_overlap", overlap)
    if len(chunk_sizes) == 1:
        parser_kwargs.setdefault("chunk_size", chunk_sizes[0])
    use = ingest_cfg.node_parser_use.strip()
    try:
        return _instantiate(use, parser_kwargs)
    except TypeError:
        parser_kwargs.pop("chunk_sizes", None)
        return _instantiate(use, parser_kwargs)


def _build_ingest_transforms(docs: Sequence[Any], *, kind: str = "general") -> list[Any]:
    """IngestionPipeline transforms: LI node parser + media/block + optional + title prefix."""
    ingest_cfg = get_knowledge_config().ingest
    transforms: list[Any] = [_build_node_parser(docs, kind=kind)]
    if ingest_cfg.media_sanitize:
        transforms.append(MediaSanitizeTransform())
    if ingest_cfg.annotate_block:
        transforms.append(BlockAnnotateTransform())
    for tcfg in ingest_cfg.transforms or []:
        use = (tcfg.use or "").strip()
        if not use:
            continue
        kwargs = tcfg.model_dump(exclude={"use"}, exclude_none=True)
        transforms.append(_instantiate(use, kwargs))
    if ingest_cfg.title_prefix:
        transforms.append(ContextualTitleTransform())
    return transforms


def ingest_document_text(
    *,
    space_id: str,
    doc_id: str,
    title: str,
    kind: str,
    sensitivity: str,
    text: str,
    parse_quality: str,
    documents: list | None = None,
    tags: list[str] | None = None,
    release: str = "current",
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    doc_attrs: dict[str, Any] | None = None,
) -> int:
    from llama_index.core import Document, StorageContext, VectorStoreIndex
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.node_parser import get_leaf_nodes

    tag_list = [t.strip() for t in (tags or []) if str(t).strip()]
    base_meta = {
        "space_id": space_id,
        "doc_id": doc_id,
        "kind": kind,
        "sensitivity": sensitivity,
        "release": (release or "current").strip() or "current",
        "title": title,
        "parse_quality": parse_quality,
        "tags": ",".join(tag_list),
    }
    if effective_from is not None:
        base_meta["effective_from"] = effective_from.isoformat()
    if effective_to is not None:
        base_meta["effective_to"] = effective_to.isoformat()
    base_meta = merge_custom_metadata(base_meta, doc_attrs)
    # id_=doc_id so PGVectorStore metadata.ref_doc_id == knowledge documents.id (delete cascade).
    # Exclude metadata from embedding — title is already prefixed into content.
    exclude_embed = list(base_meta.keys())
    li_docs: list[Document] = []
    if documents:
        for d in documents:
            body = (getattr(d, "text", None) or "").strip()
            if not body:
                continue
            meta = {**dict(getattr(d, "metadata", None) or {}), **base_meta}
            li_docs.append(
                Document(
                    text=body,
                    metadata=meta,
                    id_=doc_id,
                    excluded_embed_metadata_keys=exclude_embed,
                )
            )
    if not li_docs:
        body = (text or " ").strip() or " "
        li_docs = [
            Document(
                text=body,
                metadata=dict(base_meta),
                id_=doc_id,
                excluded_embed_metadata_keys=exclude_embed,
            )
        ]

    # Replace prior vectors for this knowledge doc (re-upload / re-ingest).
    try:
        delete_document_vectors(space_id=space_id, doc_id=doc_id)
    except Exception as exc:
        logger.warning("pre-ingest vector cleanup failed space=%s doc=%s: %s", space_id, doc_id, exc)

    transformations = _build_ingest_transforms(li_docs, kind=kind)
    all_nodes = IngestionPipeline(transformations=transformations).run(documents=li_docs, show_progress=False)
    try:
        leaf_nodes = get_leaf_nodes(all_nodes) or list(all_nodes)
    except Exception:
        leaf_nodes = list(all_nodes)

    # Drop empty nodes only (generic); no domain-specific chrome filters.
    leaf_nodes = [n for n in leaf_nodes if _node_text(n).strip()] or leaf_nodes

    for node in all_nodes:
        if not getattr(node, "node_id", None):
            node.node_id = str(uuid.uuid4())
        meta = dict(node.metadata or {})
        meta.update({k: v for k, v in base_meta.items() if not meta.get(k)})
        node.metadata = meta
        try:
            node.excluded_embed_metadata_keys = list(dict.fromkeys(list(getattr(node, "excluded_embed_metadata_keys", None) or []) + exclude_embed))
        except Exception:
            pass

    docstore = load_docstore(space_id)
    for nid, node in list(docstore.docs.items()):
        if (getattr(node, "metadata", None) or {}).get("doc_id") == doc_id:
            try:
                docstore.delete_document(nid)
            except Exception:
                pass
    docstore.add_documents(all_nodes)
    persist_docstore(space_id, docstore)

    storage_context = StorageContext.from_defaults(
        vector_store=get_vector_store(space_id),
        docstore=docstore,
    )
    VectorStoreIndex(
        leaf_nodes,
        storage_context=storage_context,
        embed_model=get_embed_model(),
        show_progress=False,
    )
    return len(leaf_nodes)


# ── retrieve (QueryFusion + BM25 + AutoMerging) ─────────────────────────────


# ── temporal (regulation validity + clause anchors) ─────────────────────────

_CLAUSE_RE = re.compile(
    r"(?:第\s*[0-9一二三四五六七八九十百千]+(?:条|款|项|章|节))|"
    r"(?:Article\s+\d+(?:\.\d+)*)",
    re.IGNORECASE,
)


def parse_as_of(value: str | date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def clause_anchors(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _CLAUSE_RE.finditer(text):
        token = re.sub(r"\s+", "", match.group(0))
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def doc_effective_at(row: Any, as_of: datetime) -> bool:
    start = getattr(row, "effective_from", None)
    end = getattr(row, "effective_to", None)
    if start is not None:
        start_dt = start if isinstance(start, datetime) else parse_as_of(start)
        if start_dt and as_of < start_dt:
            return False
    if end is not None:
        end_dt = end if isinstance(end, datetime) else parse_as_of(end)
        if end_dt and as_of > end_dt:
            return False
    return True


def clause_boost(
    item: dict[str, Any],
    anchors: list[str],
    *,
    boost: float = 0.15,
) -> float:
    if not anchors:
        return 0.0
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    haystack = " ".join(
        str(x)
        for x in (
            item.get("citable_as"),
            item.get("title"),
            item.get("snippet"),
            meta.get("heading_path"),
            meta.get("article_no"),
            meta.get("clause_id"),
        )
        if x
    )
    haystack = re.sub(r"\s+", "", haystack)
    hits = sum(1 for c in anchors if c in haystack)
    if hits <= 0:
        return 0.0
    return min(boost * hits, 0.45)


def rank_by_temporal(
    items: list[dict[str, Any]],
    *,
    query: str,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    anchors = clause_anchors(query)
    as_of_dt = as_of or datetime.now(UTC)
    enriched: list[dict[str, Any]] = []
    for item in items:
        copy = dict(item)
        meta = dict(copy.get("metadata") or {})
        eff_from = meta.get("effective_from")
        eff_to = meta.get("effective_to")
        if eff_from or eff_to:

            class _Row:
                effective_from = parse_as_of(eff_from)
                effective_to = parse_as_of(eff_to)

            meta["temporal_valid"] = doc_effective_at(_Row(), as_of_dt)
        else:
            meta.setdefault("temporal_valid", True)
        if anchors:
            meta["clause_anchors"] = anchors
            meta["clause_hit"] = clause_boost(copy, anchors) > 0
        copy["metadata"] = meta
        base = float(copy.get("score") or 0)
        copy["score"] = base + clause_boost(copy, anchors)
        enriched.append(copy)
    filtered = [x for x in enriched if x.get("metadata", {}).get("temporal_valid", True) is not False]
    filtered.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("id") or "")))
    return filtered


# ── scenario lanes ───────────────────────────────────────────────────────────

_RRF_K = 60


@dataclass(frozen=True)
class ResolvedLane:
    id: str
    kinds: list[str]
    tags: list[str] = field(default_factory=list)
    budget: int = 8
    optional: bool = False


def get_scenario_config(scenario_id: str | None) -> KnowledgeScenarioConfig:
    from deerflow.knowledge.catalog import cached_scenario, default_scenario_code

    fallback = default_scenario_code()
    sid = (scenario_id or "").strip() or fallback
    cached = cached_scenario(sid)
    if cached is not None:
        return cached
    cfg = get_knowledge_config()
    item = cfg.scenario_by_type(sid)
    if item is None:
        item = cfg.scenario_by_type(fallback)
    if item is None and cfg.scenarios:
        item = cfg.scenarios[0]
    if item is None:
        item = KnowledgeScenarioConfig(type=fallback)
    return item


def resolve_lanes(
    scenario: KnowledgeScenarioConfig,
    *,
    top_k: int | None = None,
) -> list[ResolvedLane]:
    final_top_k = max(1, int(top_k if top_k is not None else scenario.top_k or 8))

    if scenario.lanes:
        out: list[ResolvedLane] = []
        for index, lane in enumerate(scenario.lanes):
            kinds = [k for k in (lane.kinds or []) if k]
            if not kinds:
                continue
            lid = (lane.id or "").strip() or _lane_id(kinds, lane.tags, index)
            budget = lane.budget if lane.budget is not None else final_top_k
            out.append(
                ResolvedLane(
                    id=lid,
                    kinds=kinds,
                    tags=[t for t in (lane.tags or []) if t],
                    budget=max(1, int(budget)),
                    optional=bool(lane.optional),
                )
            )
        return out

    shorthand = [k for k in (scenario.kinds or []) if k]
    if not shorthand:
        return []

    base, rem = divmod(final_top_k, len(shorthand))
    lanes: list[ResolvedLane] = []
    for index, kind in enumerate(shorthand):
        budget = base + (1 if index < rem else 0)
        lanes.append(
            ResolvedLane(
                id=kind,
                kinds=[kind],
                tags=[],
                budget=max(1, budget),
            )
        )
    return lanes


def scenario_kind_ids(scenario: KnowledgeScenarioConfig) -> list[str]:
    seen: list[str] = []
    for lane in resolve_lanes(scenario):
        for kind in lane.kinds:
            if kind and kind not in seen:
                seen.append(kind)
    return seen


def lane_pool_k(budget: int, *, has_tags: bool) -> int:
    if not has_tags:
        return max(1, budget)
    return min(max(budget + 4, budget * 2), 40)


def _lane_id(kinds: list[str], tags: list[str], index: int) -> str:
    if tags:
        return f"{'-'.join(kinds)}:{'-'.join(tags)}"
    if kinds:
        return kinds[0] if len(kinds) == 1 else "-".join(kinds)
    return f"lane-{index}"


def item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or "").strip()


def item_score(item: dict[str, Any]) -> float:
    return float(item.get("score") or 0)


def stable_rank_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score desc, then id asc — same inputs → same order across runs."""
    return sorted(items, key=lambda it: (-item_score(it), item_id(it)))


def merge_lane_hits(
    buckets: list[tuple[str, list[dict[str, Any]], int]],
    *,
    final_top_k: int,
    merge_mode: str = "slot_then_rrf",
) -> list[dict[str, Any]]:
    mode = (merge_mode or "slot_then_rrf").strip().lower()
    if mode == "score":
        by_id: dict[str, dict[str, Any]] = {}
        for _lane_id, items, _budget in buckets:
            for it in items:
                iid = item_id(it)
                if not iid:
                    continue
                prev = by_id.get(iid)
                if prev is None or item_score(it) > item_score(prev):
                    by_id[iid] = it
        return stable_rank_items(list(by_id.values()))[: max(1, final_top_k)]

    picked: list[dict[str, Any]] = []
    picked_ids: set[str] = set()

    for lane_id, items, budget in buckets:
        if not items:
            continue
        slot_take = min(max(1, min(2, budget)), len(items))
        for it in stable_rank_items(items)[:slot_take]:
            iid = item_id(it)
            if not iid or iid in picked_ids:
                continue
            copy = dict(it)
            meta = dict(copy.get("metadata") or {})
            meta["lane_id"] = lane_id
            copy["metadata"] = meta
            picked.append(copy)
            picked_ids.add(iid)

    remaining = max(0, final_top_k - len(picked))
    if remaining <= 0:
        return picked[: max(1, final_top_k)]

    rrf: dict[str, float] = {}
    item_by_id: dict[str, dict[str, Any]] = {}
    for lane_id, items, _budget in buckets:
        for rank, it in enumerate(stable_rank_items(items)):
            iid = item_id(it)
            if not iid or iid in picked_ids:
                continue
            rrf[iid] = rrf.get(iid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            item_by_id.setdefault(iid, it)

    for iid, _ in sorted(rrf.items(), key=lambda x: (-x[1], x[0]))[:remaining]:
        picked.append(dict(item_by_id[iid]))
        picked_ids.add(iid)

    return picked[: max(1, final_top_k)]


@dataclass(frozen=True)
class ScenarioPack:
    id: str
    top_k: int | None = None
    score: float | None = None
    description: str = ""


def get_scenario_pack(scenario_id: str | None) -> ScenarioPack:
    item = get_scenario_config(scenario_id)
    return ScenarioPack(
        id=item.type,
        top_k=item.top_k,
        score=item.effective_score,
        description=item.description,
    )


def resolve_scenario(
    *,
    request_scenario: str | None,
    space_default_scenarios: list[str] | None = None,
) -> ScenarioPack:
    from deerflow.knowledge.catalog import default_scenario_code

    if request_scenario and request_scenario.strip():
        return get_scenario_pack(request_scenario)
    defaults = list(space_default_scenarios or [])
    if defaults:
        return get_scenario_pack(defaults[0])
    return get_scenario_pack(default_scenario_code())


def _build_retriever(*, space_id: str, retrieve_n: int, num_queries: int):
    from llama_index.core import StorageContext, VectorStoreIndex
    from llama_index.core.retrievers import AutoMergingRetriever, QueryFusionRetriever
    from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters
    from llama_index.retrievers.bm25 import BM25Retriever

    # Always pin YAML embed before any LlamaIndex path that may touch Settings.
    ensure_embed_model()

    cfg = get_knowledge_config().retrieval
    docstore = load_docstore(space_id)
    storage_context = StorageContext.from_defaults(
        vector_store=get_vector_store(space_id),
        docstore=docstore,
    )
    index = VectorStoreIndex.from_vector_store(
        get_vector_store(space_id),
        embed_model=get_embed_model(),
        storage_context=storage_context,
    )
    filters = MetadataFilters(filters=[MetadataFilter(key="space_id", value=space_id, operator=FilterOperator.EQ)])
    retrievers: list[Any] = [index.as_retriever(similarity_top_k=retrieve_n, filters=filters)]
    if cfg.bm25:
        try:
            n_docs = max(1, len(getattr(docstore, "docs", {}) or {}))
            bm25_k = min(retrieve_n, n_docs)
            kwargs: dict[str, Any] = {
                "docstore": docstore,
                "similarity_top_k": bm25_k,
                "tokenizer": _bm25_tokenize,
            }
            try:
                retrievers.append(BM25Retriever.from_defaults(**kwargs))
            except TypeError:
                kwargs.pop("tokenizer", None)
                retrievers.append(BM25Retriever.from_defaults(**kwargs))
        except Exception as exc:
            logger.debug("BM25Retriever skipped: %s", exc)

    fusion_queries = 1
    if num_queries > 1 and ensure_llama_settings():
        fusion_queries = num_queries
    # QueryFusionRetriever.__init__ always resolves Settings.llm (lazy OpenAI
    # default) even when num_queries=1 never calls it. Pass MockLLM for the
    # hybrid-only path so missing OPENAI_API_KEY cannot break retrieval.
    fusion_kwargs: dict[str, Any] = {
        "similarity_top_k": retrieve_n,
        "num_queries": fusion_queries,
        "mode": cfg.fusion_mode or "reciprocal_rerank",
        "use_async": False,
        "verbose": False,
    }
    if fusion_queries <= 1:
        from llama_index.core.llms import MockLLM

        fusion_kwargs["llm"] = MockLLM()
    fusion = QueryFusionRetriever(retrievers, **fusion_kwargs)
    if cfg.parent_expand and docstore.docs:
        try:
            return AutoMergingRetriever(fusion, storage_context, verbose=False)
        except Exception as exc:
            logger.debug("AutoMergingRetriever fallback: %s", exc)
    return fusion


def _apply_rerank(nodes: list, *, query: str, top_n: int) -> list:
    """Assemble LlamaIndex BaseNodePostprocessor from config ``rerank_use`` (swap model via YAML)."""
    cfg = get_knowledge_config().retrieval
    if not cfg.rerank or not nodes:
        return nodes
    use = (cfg.rerank_use or "").strip()
    if not use:
        return nodes

    n = int(cfg.rerank_top_n or 0) or top_n or cfg.top_k
    kwargs: dict[str, Any] = {"top_n": min(n, len(nodes))}
    model = (cfg.rerank_model or "").strip()
    if model:
        kwargs["model"] = model
    rerank_api_key = (getattr(cfg, "rerank_api_key", "") or os.getenv("RERANK_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if rerank_api_key:
        kwargs["api_key"] = rerank_api_key
    postprocessor = _instantiate(use, kwargs)
    return list(postprocessor.postprocess_nodes(nodes, query_str=query))


def _apply_score_cutoff(nodes: list, cutoff: float | None) -> list:
    """Drop nodes below similarity_cutoff. Intended for post-rerank calibrated scores."""
    if cutoff is None or cutoff <= 0 or not nodes:
        return nodes
    kept = [n for n in nodes if float(getattr(n, "score", 0) or 0) >= cutoff]
    return kept


def parse_tags_value(raw: Any) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {str(t).strip() for t in raw if str(t).strip()}
    return {t.strip() for t in str(raw).split(",") if t.strip()}


def metadata_tags_match(meta: dict[str, Any], want_tags: list[str]) -> bool:
    want = {t.strip() for t in want_tags if t.strip()}
    if not want:
        return True
    have = parse_tags_value(meta.get("tags"))
    return bool(have & want)


def search_space(
    *,
    space_ids: list[str],
    query: str,
    top_k: int | None = None,
    kinds: list[str] | None = None,
    tags: list[str] | None = None,
    similarity_cutoff: float | None = None,
    as_of_date: str | None = None,
    release_by_space: dict[str, str] | None = None,
    fusion_queries: int | None = None,
) -> list[dict]:
    global _fusion_llm_disabled
    from llama_index.core.schema import NodeRelationship

    cfg = get_knowledge_config().retrieval
    k = top_k or cfg.top_k
    retrieve_n = max(cfg.retrieve_n, k)
    cutoff = cfg.similarity_cutoff if similarity_cutoff is None else similarity_cutoff
    snippet_max = int(cfg.snippet_max_chars or 1200)
    items: list[dict] = []
    for space_id in space_ids:
        want_release = (release_by_space or {}).get(space_id, "current")
        if fusion_queries is not None:
            want_queries = max(1, int(fusion_queries))
        else:
            want_queries = 1 if _fusion_llm_disabled else (cfg.fusion_num_queries if cfg.hybrid else 1)
        try:
            retriever = _build_retriever(
                space_id=space_id,
                retrieve_n=retrieve_n,
                num_queries=want_queries,
            )
            nodes = list(retriever.retrieve(query))
        except Exception as exc:
            # Query-fusion LLM may be misconfigured; fall back to single-query hybrid.
            if want_queries > 1:
                _fusion_llm_disabled = True
                logger.warning(
                    "Retrieve with fusion failed for %s (%s); disable multi-query and retry num_queries=1",
                    space_id,
                    exc,
                )
                try:
                    retriever = _build_retriever(
                        space_id=space_id,
                        retrieve_n=retrieve_n,
                        num_queries=1,
                    )
                    nodes = list(retriever.retrieve(query))
                except Exception as exc2:
                    logger.warning("Retrieve failed for %s: %s", space_id, exc2)
                    continue
            else:
                logger.warning("Retrieve failed for %s: %s", space_id, exc)
                continue
        # Rerank first — RRF fusion scores are not cosine; cutoff applies to rerank scores.
        reranked = False
        if cfg.rerank and cfg.rerank_model:
            try:
                rerank_n = int(cfg.rerank_top_n or 0) or max(k * 2, k)
                nodes = _apply_rerank(nodes, query=query, top_n=rerank_n)
                reranked = True
            except Exception as exc:
                logger.warning("Rerank skipped for %s: %s", space_id, exc)
        if reranked or not (cfg.hybrid and (cfg.fusion_mode or "").lower().startswith("reciprocal")):
            nodes = _apply_score_cutoff(nodes, cutoff)
        seen: set[str] = set()
        for n in nodes:
            node_obj = getattr(n, "node", n)
            meta = dict(getattr(node_obj, "metadata", None) or {})
            if not _release_matches(meta, want_release):
                continue
            if kinds and meta.get("kind") not in kinds:
                continue
            if tags and not metadata_tags_match(meta, tags):
                continue
            pid = getattr(node_obj, "node_id", None) or str(id(n))
            if pid in seen:
                continue
            seen.add(pid)
            raw_snippet = n.get_content() if hasattr(n, "get_content") else getattr(node_obj, "text", str(n))
            snippet = format_evidence_snippet(str(raw_snippet or ""), query, max_chars=snippet_max)
            title = meta.get("title") or ""
            heading = meta.get("heading_path") or ""
            parent_id = meta.get("parent_id")
            rel = getattr(node_obj, "relationships", None) or {}
            parent_info = rel.get(NodeRelationship.PARENT)
            if parent_info is not None and parent_id is None:
                parent_id = getattr(parent_info, "node_id", None)
            block = meta.get("block") or annotate_block_type(str(raw_snippet or ""))
            evidence_meta: dict[str, Any] = {
                "space_id": meta.get("space_id") or space_id,
                "doc_id": meta.get("doc_id"),
                "block": block,
                "heading_path": heading or None,
                "parent_id": parent_id,
                "page_no": meta.get("page_no"),
                "asset_uri": meta.get("asset_uri"),
            }
            evidence_meta.update(custom_metadata_from_chunk(meta))
            items.append(
                {
                    "id": pid,
                    "source": "chunk",
                    "kind": meta.get("kind", "general"),
                    "title": title or heading or "",
                    "snippet": snippet,
                    "score": float(n.score or 0),
                    "citable_as": f"{title} / {heading}".strip(" /") if heading else title,
                    "metadata": evidence_meta,
                }
            )
    as_of_dt = parse_as_of(as_of_date)
    items = rank_by_temporal(items, query=query, as_of=as_of_dt)
    return stable_rank_items(items)[:k]


def compute_precision_recall_at_k(
    *,
    retrieved_doc_ids: list[str],
    relevant_doc_ids: list[str],
    k: int,
) -> tuple[float, float]:
    """Doc-level Precision@k and Recall@k.

    Precision@k = |retrieved∩relevant| / |retrieved@k|
    Recall@k = |retrieved∩relevant| / |relevant|
    """
    retrieved = [d for d in retrieved_doc_ids if d][: max(k, 0)]
    relevant = {d for d in relevant_doc_ids if d}
    if not retrieved and not relevant:
        return 1.0, 1.0
    if not retrieved:
        return 0.0, 0.0 if relevant else 1.0
    hit = len(set(retrieved) & relevant)
    precision = hit / len(retrieved)
    recall = (hit / len(relevant)) if relevant else (1.0 if hit == 0 else 0.0)
    # When no relevant_ids labeled, treat needle-only eval: recall undefined → use 0/1 from caller
    if not relevant:
        return precision, 0.0
    return precision, recall


def evaluate_search_cases(
    *,
    space_ids: list[str],
    cases: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, Any]:
    """Run retrieval eval cases and aggregate Precision@k / Recall@k / needle hit rate.

    Each case: ``{q, needles?: [], relevant_doc_ids?: []}``.
    When ``relevant_doc_ids`` empty, precision uses needle-matched docs as pseudo-relevant
    for that query only when computing needle_hit; P/R require explicit relevant_doc_ids.
    """
    per_case: list[dict[str, Any]] = []
    precisions: list[float] = []
    recalls: list[float] = []
    needle_hits = 0
    labeled = 0

    for raw in cases:
        q = str(raw.get("q") or raw.get("query") or "").strip()
        if not q:
            continue
        needles = [str(n) for n in (raw.get("needles") or []) if n]
        relevant = [str(d) for d in (raw.get("relevant_doc_ids") or raw.get("relevant_ids") or []) if d]
        hits = search_space(space_ids=space_ids, query=q, top_k=top_k)
        # Prefer doc order as returned (already score-sorted)
        retrieved_docs: list[str] = []
        for h in hits:
            did = (h.get("metadata") or {}).get("doc_id")
            if did and did not in retrieved_docs:
                retrieved_docs.append(str(did))
        blob = "\n".join(str(h.get("snippet") or "") for h in hits)
        needle_ok = (not needles) or any(n in blob for n in needles)
        needle_hits += int(needle_ok)

        if relevant:
            labeled += 1
            p, r = compute_precision_recall_at_k(
                retrieved_doc_ids=retrieved_docs,
                relevant_doc_ids=relevant,
                k=top_k,
            )
            precisions.append(p)
            recalls.append(r)
        else:
            p, r = None, None

        per_case.append(
            {
                "q": q,
                "hits": len(hits),
                "items": [
                    {
                        "id": h.get("id"),
                        "title": h.get("title") or "",
                        "snippet": h.get("snippet") or "",
                        "score": h.get("score"),
                        "citable_as": h.get("citable_as") or "",
                        "kind": h.get("kind") or "general",
                        "doc_id": (h.get("metadata") or {}).get("doc_id"),
                        "space_id": (h.get("metadata") or {}).get("space_id"),
                        "heading_path": (h.get("metadata") or {}).get("heading_path"),
                        "page_no": (h.get("metadata") or {}).get("page_no"),
                        "block": (h.get("metadata") or {}).get("block") or "text",
                        "source_filename": None,
                        "doc_title": None,
                    }
                    for h in hits
                ],
                "retrieved_doc_ids": retrieved_docs,
                "relevant_doc_ids": relevant,
                "needle_hit": needle_ok,
                "precision_at_k": p,
                "recall_at_k": r,
                "top_score": hits[0].get("score") if hits else None,
            }
        )

    n = max(len(per_case), 1)
    return {
        "top_k": top_k,
        "case_count": len(per_case),
        "needle_hit_rate": needle_hits / n,
        "precision_at_k": (sum(precisions) / len(precisions)) if precisions else None,
        "recall_at_k": (sum(recalls) / len(recalls)) if recalls else None,
        "labeled_case_count": labeled,
        "cases": per_case,
    }
