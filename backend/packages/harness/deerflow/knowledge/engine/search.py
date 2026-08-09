"""Hybrid search, multi-space merge, and temporal ranking."""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from deerflow.config.knowledge_config import KnowledgeScenarioConfig, get_knowledge_config
from deerflow.knowledge.adapters.storage import (
    ensure_embed_model,
    ensure_llama_settings,
    get_embed_model,
    get_vector_store,
    load_docstore,
    release_matches,
)
from deerflow.knowledge.engine.evidence import (
    annotate_block_type,
    bm25_tokenize,
    custom_metadata_from_chunk,
    format_evidence_snippet,
    instantiate_class,
    parse_as_of,
)

logger = logging.getLogger(__name__)

_fusion_llm_disabled: bool = False


# ── temporal (regulation validity + clause anchors) ─────────────────────────

_CLAUSE_RE = re.compile(
    r"(?:第\s*[0-9一二三四五六七八九十百千]+(?:条|款|项|章|节))|"
    r"(?:Article\s+\d+(?:\.\d+)*)",
    re.IGNORECASE,
)


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


def _metadata_enabled(meta: dict[str, Any]) -> bool:
    enabled = meta.get("enabled")
    if enabled is False:
        return False
    if isinstance(enabled, str) and enabled.strip().lower() in {"false", "0", "no"}:
        return False
    return True


def metadata_retrieval_allowed(meta: dict[str, Any], as_of: datetime) -> bool:
    if not _metadata_enabled(meta):
        return False
    eff_from = meta.get("effective_from")
    eff_to = meta.get("effective_to")
    if eff_from or eff_to:

        class _Row:
            effective_from = parse_as_of(eff_from)
            effective_to = parse_as_of(eff_to)

        return doc_effective_at(_Row(), as_of)
    return True


def document_retrieval_allowed(row: Any, as_of: datetime) -> bool:
    """Authoritative retrieval gate from the live knowledge document row."""
    attrs = row.attrs if isinstance(getattr(row, "attrs", None), dict) else {}
    meta = dict(attrs)
    eff_from = getattr(row, "effective_from", None)
    eff_to = getattr(row, "effective_to", None)
    if eff_from is not None:
        meta["effective_from"] = eff_from.isoformat()
    if eff_to is not None:
        meta["effective_to"] = eff_to.isoformat()
    return metadata_retrieval_allowed(meta, as_of)


_UNIVERSAL_TAG_CODES = frozenset({"general", "通用"})


def _normalize_tag_codes(raw: Any) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, list):
        parts = raw
    elif isinstance(raw, str):
        parts = raw.split(",")
    else:
        return set()
    return {str(t).strip().lower() for t in parts if str(t).strip()}


def _hit_doc_tags(meta: dict[str, Any], row: Any | None) -> set[str]:
    if row is not None:
        tags = _normalize_tag_codes(getattr(row, "tags", None))
        if tags:
            return tags
    return _normalize_tag_codes(meta.get("tags"))


def _hit_doc_kind(meta: dict[str, Any], row: Any | None) -> str:
    if row is not None:
        kind = str(getattr(row, "kind", "") or "").strip()
        if kind:
            return kind.lower()
    return str(meta.get("kind") or "").strip().lower()


def catalog_tags_match(doc_tags: set[str], filter_tags: set[str]) -> bool:
    """Doc matches when it shares a filter tag or is tagged universal (general)."""
    if not filter_tags:
        return True
    if not doc_tags:
        return False
    if doc_tags & filter_tags:
        return True
    return bool(doc_tags & _UNIVERSAL_TAG_CODES)


def filter_hits_by_catalog(
    hits: list[dict[str, Any]],
    doc_meta: dict[str, Any],
    *,
    tags: list[str] | None = None,
    kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    filter_tags = _normalize_tag_codes(tags)
    filter_kinds = _normalize_tag_codes(kinds)
    if not filter_tags and not filter_kinds:
        return hits
    kept: list[dict[str, Any]] = []
    for hit in hits:
        meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        did = str(meta.get("doc_id") or "").strip()
        row = doc_meta.get(did) if did else None
        if not catalog_tags_match(_hit_doc_tags(meta, row), filter_tags):
            continue
        if filter_kinds and _hit_doc_kind(meta, row) not in filter_kinds:
            continue
        kept.append(hit)
    return kept


def filter_hits_by_document_state(
    hits: list[dict[str, Any]],
    doc_meta: dict[str, Any],
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Drop hits whose source document is disabled or outside its effective window."""
    if not hits or not doc_meta:
        return hits
    as_of_dt = as_of or datetime.now(UTC)
    kept: list[dict[str, Any]] = []
    for hit in hits:
        did = str((hit.get("metadata") or {}).get("doc_id") or "").strip()
        if not did:
            kept.append(hit)
            continue
        row = doc_meta.get(did)
        if row is not None and not document_retrieval_allowed(row, as_of_dt):
            continue
        kept.append(hit)
    return kept


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
        meta["temporal_valid"] = metadata_retrieval_allowed(meta, as_of_dt)
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


# ── multi-space merge ─────────────────────────────────────────────────────────

_RRF_K = 60


def get_scenario_config(scenario_id: str | None) -> KnowledgeScenarioConfig:
    from deerflow.knowledge.app.codes import cached_scenario, default_scenario_code

    fallback = default_scenario_code()
    sid = (scenario_id or "").strip() or fallback
    cached = cached_scenario(sid)
    if cached is not None:
        return cached
    return KnowledgeScenarioConfig(type=sid or fallback)


def space_budgets(space_count: int, final_top_k: int) -> list[int]:
    if space_count <= 0:
        return []
    k = max(1, int(final_top_k))
    base, rem = divmod(k, space_count)
    return [base + (1 if index < rem else 0) for index in range(space_count)]


def item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or "").strip()


def item_score(item: dict[str, Any]) -> float:
    return float(item.get("score") or 0)


def stable_rank_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score desc, then id asc — same inputs → same order across runs."""
    return sorted(items, key=lambda it: (-item_score(it), item_id(it)))


def merge_space_hits(
    buckets: list[tuple[str, list[dict[str, Any]], int]],
    *,
    final_top_k: int,
    merge_mode: str = "slot_then_rrf",
) -> list[dict[str, Any]]:
    """Merge per-bucket retrieval (space or document): slot guarantee + RRF backfill."""
    mode = (merge_mode or "slot_then_rrf").strip().lower()
    if mode == "score":
        by_id: dict[str, dict[str, Any]] = {}
        for _space_id, items, _budget in buckets:
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

    for bucket_id, items, budget in buckets:
        if not items:
            continue
        slot_take = min(max(1, min(2, budget)), len(items))
        for it in stable_rank_items(items)[:slot_take]:
            iid = item_id(it)
            if not iid or iid in picked_ids:
                continue
            copy = dict(it)
            meta = dict(copy.get("metadata") or {})
            meta.setdefault("recall_path", bucket_id)
            copy["metadata"] = meta
            picked.append(copy)
            picked_ids.add(iid)

    remaining = max(0, final_top_k - len(picked))
    if remaining <= 0:
        return picked[: max(1, final_top_k)]

    rrf: dict[str, float] = {}
    item_by_id: dict[str, dict[str, Any]] = {}
    for _space_id, items, _budget in buckets:
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
    from deerflow.knowledge.app.codes import default_scenario_code

    if request_scenario and request_scenario.strip():
        return get_scenario_pack(request_scenario)
    defaults = list(space_default_scenarios or [])
    if defaults:
        return get_scenario_pack(defaults[0])
    return get_scenario_pack(default_scenario_code())


def build_hybrid_retriever(*, space_id: str, retrieve_n: int, num_queries: int, doc_id: str | None = None):
    from llama_index.core import StorageContext, VectorStoreIndex
    from llama_index.core.retrievers import AutoMergingRetriever, QueryFusionRetriever
    from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters
    from llama_index.retrievers.bm25 import BM25Retriever

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
    filters = [MetadataFilter(key="space_id", value=space_id, operator=FilterOperator.EQ)]
    if doc_id:
        filters.append(MetadataFilter(key="doc_id", value=doc_id, operator=FilterOperator.EQ))
    metadata_filters = MetadataFilters(filters=filters)
    retrievers: list[Any] = [index.as_retriever(similarity_top_k=retrieve_n, filters=metadata_filters)]
    if cfg.bm25 and not doc_id:
        try:
            n_docs = max(1, len(getattr(docstore, "docs", {}) or {}))
            bm25_k = min(retrieve_n, n_docs)
            kwargs: dict[str, Any] = {
                "docstore": docstore,
                "similarity_top_k": bm25_k,
                "tokenizer": bm25_tokenize,
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


def apply_rerank(nodes: list, *, query: str, top_n: int) -> list:
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
    postprocessor = instantiate_class(use, kwargs)
    return list(postprocessor.postprocess_nodes(nodes, query_str=query))


def apply_score_cutoff(nodes: list, cutoff: float | None) -> list:
    """Drop nodes below similarity_cutoff. Intended for post-rerank calibrated scores."""
    if cutoff is None or cutoff <= 0 or not nodes:
        return nodes
    kept = [n for n in nodes if float(getattr(n, "score", 0) or 0) >= cutoff]
    return kept


def list_space_doc_ids(space_id: str, *, release: str = "current") -> list[str]:
    """Distinct knowledge document ids indexed in a space (respects release filter)."""
    docstore = load_docstore(space_id)
    seen: list[str] = []
    for node in getattr(docstore, "docs", {}).values():
        meta = dict(getattr(node, "metadata", None) or {})
        if not release_matches(meta, release):
            continue
        did = str(meta.get("doc_id") or "").strip()
        if did and did not in seen:
            seen.append(did)
    return seen


def nodes_to_evidence_items(
    nodes: list,
    *,
    space_id: str,
    query: str,
    snippet_max: int,
    want_release: str,
) -> list[dict]:
    from llama_index.core.schema import NodeRelationship

    items: list[dict] = []
    seen: set[str] = set()
    for n in nodes:
        node_obj = getattr(n, "node", n)
        meta = dict(getattr(node_obj, "metadata", None) or {})
        if not release_matches(meta, want_release):
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
    return items


def retrieve_document_nodes(
    *,
    space_id: str,
    query: str,
    retrieve_n: int,
    want_queries: int,
    doc_id: str | None = None,
) -> list:
    """Hybrid retrieve nodes for a whole space or one document."""
    global _fusion_llm_disabled

    try:
        retriever = build_hybrid_retriever(
            space_id=space_id,
            retrieve_n=retrieve_n,
            num_queries=want_queries,
            doc_id=doc_id,
        )
        return list(retriever.retrieve(query))
    except Exception as exc:
        if want_queries > 1:
            _fusion_llm_disabled = True
            label = doc_id or space_id
            logger.warning(
                "Retrieve with fusion failed for %s (%s); disable multi-query and retry num_queries=1",
                label,
                exc,
            )
            try:
                retriever = build_hybrid_retriever(
                    space_id=space_id,
                    retrieve_n=retrieve_n,
                    num_queries=1,
                    doc_id=doc_id,
                )
                return list(retriever.retrieve(query))
            except Exception as exc2:
                logger.warning("Retrieve failed for %s: %s", label, exc2)
                return []
        label = doc_id or space_id
        logger.warning("Retrieve failed for %s: %s", label, exc)
        return []


def retrieve_space_items(
    *,
    space_id: str,
    query: str,
    top_k: int,
    similarity_cutoff: float | None,
    release: str,
    fusion_queries: int | None,
    doc_id: str | None = None,
) -> list[dict]:
    cfg = get_knowledge_config().retrieval
    k = max(1, int(top_k))
    retrieve_n = max(cfg.retrieve_n, k)
    cutoff = cfg.similarity_cutoff if similarity_cutoff is None else similarity_cutoff
    snippet_max = int(cfg.snippet_max_chars or 1200)
    want_release = release or "current"
    if fusion_queries is not None:
        want_queries = max(1, int(fusion_queries))
    else:
        want_queries = 1 if _fusion_llm_disabled else (cfg.fusion_num_queries if cfg.hybrid else 1)

    nodes = retrieve_document_nodes(
        space_id=space_id,
        query=query,
        retrieve_n=retrieve_n,
        want_queries=want_queries,
        doc_id=doc_id,
    )
    reranked = False
    if cfg.rerank and cfg.rerank_model:
        try:
            rerank_n = int(cfg.rerank_top_n or 0) or max(k * 2, k)
            nodes = apply_rerank(nodes, query=query, top_n=rerank_n)
            reranked = True
        except Exception as exc:
            label = doc_id or space_id
            logger.warning("Rerank skipped for %s: %s", label, exc)
    if reranked or not (cfg.hybrid and (cfg.fusion_mode or "").lower().startswith("reciprocal")):
        nodes = apply_score_cutoff(nodes, cutoff)
    items = nodes_to_evidence_items(
        nodes,
        space_id=space_id,
        query=query,
        snippet_max=snippet_max,
        want_release=want_release,
    )
    return stable_rank_items(items)[:k]


def merge_items_by_doc_buckets(
    items: list[dict],
    *,
    final_top_k: int,
    merge_mode: str,
) -> list[dict]:
    by_doc: dict[str, list[dict]] = {}
    for it in items:
        did = str((it.get("metadata") or {}).get("doc_id") or "").strip()
        if did:
            by_doc.setdefault(did, []).append(it)
    if len(by_doc) <= 1:
        return stable_rank_items(items)[:final_top_k]
    doc_ids = sorted(by_doc.keys())
    budgets = space_budgets(len(doc_ids), final_top_k)
    buckets = [(did, by_doc[did], budget) for did, budget in zip(doc_ids, budgets)]
    return merge_space_hits(buckets, final_top_k=final_top_k, merge_mode=merge_mode)


def retrieve_in_space(
    *,
    space_id: str,
    query: str,
    top_k: int,
    similarity_cutoff: float | None = None,
    release: str = "current",
    fusion_queries: int | None = None,
    merge_mode: str = "slot_then_rrf",
) -> list[dict]:
    """Retrieve from one space; parallel per-document paths when multiple files are indexed."""
    cfg = get_knowledge_config().retrieval
    k = max(1, int(top_k))
    want_release = release or "current"
    doc_ids = list_space_doc_ids(space_id, release=want_release)
    use_per_doc = bool(cfg.per_doc_merge) and len(doc_ids) > 1

    if not use_per_doc:
        return retrieve_space_items(
            space_id=space_id,
            query=query,
            top_k=k,
            similarity_cutoff=similarity_cutoff,
            release=want_release,
            fusion_queries=fusion_queries,
        )

    max_docs = max(1, int(cfg.max_doc_paths or 32))
    per_doc_pool = max(2, min(cfg.retrieve_n, k * 2))

    if len(doc_ids) > max_docs:
        pool = max(k * 2, cfg.retrieve_n, len(doc_ids))
        pooled = retrieve_space_items(
            space_id=space_id,
            query=query,
            top_k=pool,
            similarity_cutoff=similarity_cutoff,
            release=want_release,
            fusion_queries=fusion_queries,
        )
        return merge_items_by_doc_buckets(pooled, final_top_k=k, merge_mode=merge_mode)

    def _run(doc_id: str) -> list[dict]:
        return retrieve_space_items(
            space_id=space_id,
            query=query,
            top_k=per_doc_pool,
            similarity_cutoff=similarity_cutoff,
            release=want_release,
            fusion_queries=fusion_queries,
            doc_id=doc_id,
        )

    max_workers = min(len(doc_ids), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_run, doc_ids))
    budgets = space_budgets(len(doc_ids), k)
    buckets = [(did, items, budget) for did, items, budget in zip(doc_ids, results, budgets)]
    merged = merge_space_hits(buckets, final_top_k=k, merge_mode=merge_mode)
    return merged[:k]


def retrieve_across_spaces(
    *,
    space_ids: list[str],
    query: str,
    final_top_k: int | None = None,
    pool_k: int | None = None,
    similarity_cutoff: float | None = None,
    as_of_date: str | None = None,
    release_by_space: dict[str, str] | None = None,
    fusion_queries: int | None = None,
    merge_mode: str = "slot_then_rrf",
) -> list[dict]:
    """Retrieve across spaces; parallel per-space when more than one space."""

    cfg = get_knowledge_config().retrieval
    k = max(1, int(final_top_k or cfg.top_k or 8))
    per_space_pool = max(1, int(pool_k or cfg.retrieve_n or k))
    if not space_ids:
        return []
    if len(space_ids) == 1:
        sid = space_ids[0]
        release = (release_by_space or {}).get(sid, "current")
        items = retrieve_in_space(
            space_id=sid,
            query=query,
            top_k=per_space_pool if pool_k else k,
            similarity_cutoff=similarity_cutoff,
            release=release,
            fusion_queries=fusion_queries,
            merge_mode=merge_mode,
        )
        as_of_dt = parse_as_of(as_of_date)
        items = rank_by_temporal(items, query=query, as_of=as_of_dt)
        return stable_rank_items(items)[:k]

    def _run(space_id: str) -> list[dict]:
        release = (release_by_space or {}).get(space_id, "current")
        return retrieve_in_space(
            space_id=space_id,
            query=query,
            top_k=per_space_pool,
            similarity_cutoff=similarity_cutoff,
            release=release,
            fusion_queries=fusion_queries,
            merge_mode=merge_mode,
        )

    max_workers = min(len(space_ids), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_run, space_ids))
    budgets = space_budgets(len(space_ids), k)
    buckets = [(sid, items, budget) for sid, items, budget in zip(space_ids, results, budgets)]
    merged = merge_space_hits(buckets, final_top_k=k, merge_mode=merge_mode)
    as_of_dt = parse_as_of(as_of_date)
    merged = rank_by_temporal(merged, query=query, as_of=as_of_dt)
    return stable_rank_items(merged)[:k]
