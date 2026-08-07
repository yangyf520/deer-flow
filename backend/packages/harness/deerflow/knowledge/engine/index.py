"""Embed leaf nodes and persist vectors + docstore."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from deerflow.knowledge.adapters.storage import (
    delete_document_vectors,
    get_embed_model,
    get_vector_store,
    load_docstore,
    persist_docstore,
)
from deerflow.knowledge.engine.chunk import build_ingest_transforms
from deerflow.knowledge.engine.evidence import merge_custom_metadata, node_text

logger = logging.getLogger(__name__)


def index_document(
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

    try:
        delete_document_vectors(space_id=space_id, doc_id=doc_id)
    except Exception as exc:
        logger.warning("pre-ingest vector cleanup failed space=%s doc=%s: %s", space_id, doc_id, exc)

    transformations = build_ingest_transforms(li_docs)
    all_nodes = IngestionPipeline(transformations=transformations).run(documents=li_docs, show_progress=False)
    try:
        leaf_nodes = get_leaf_nodes(all_nodes) or list(all_nodes)
    except Exception:
        leaf_nodes = list(all_nodes)

    leaf_nodes = [n for n in leaf_nodes if node_text(n).strip()] or leaf_nodes

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
