"""Vector store, docstore, and chunk persistence."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.config.runtime_paths import runtime_home
from deerflow.knowledge.engine.evidence import annotate_block_type, instantiate_class, node_text

logger = logging.getLogger(__name__)


def get_embed_model():
    """Assemble embedding from ``knowledge.embed.use`` (YAML ctor kwargs → LlamaIndex class)."""
    cfg = get_knowledge_config().embed
    return instantiate_class(cfg.resolved().use, cfg.ctor_kwargs())


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
        Settings.llm = instantiate_class(qcfg.use or "llama_index.llms.openai:OpenAI", kwargs)
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


def release_matches(meta: dict[str, Any], want: str) -> bool:
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
        text = node_text(node).strip()
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
