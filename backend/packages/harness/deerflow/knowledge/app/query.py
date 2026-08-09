"""Knowledge retrieval and eval API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.knowledge.app.spaces import (
    list_accessible_spaces,
    space_knowledge_version,
    space_retrieval_from_row,
)
from deerflow.knowledge.contract import (
    EvidenceItem,
    EvidencePackResponse,
    RecallEvalCase,
    RecallEvalResponse,
)
from deerflow.knowledge.engine.evidence import user_attrs_from_metadata
from deerflow.knowledge.engine.search import (
    filter_hits_by_document_state,
    get_scenario_config,
    merge_space_hits,
    parse_as_of,
    rank_by_temporal,
    resolve_scenario,
    retrieve_in_space,
    space_budgets,
    stable_rank_items,
)
from deerflow.knowledge.runtime import resolve_agent_knowledge_scope
from deerflow.persistence.knowledge.model import KnowledgeDocumentRow

logger = logging.getLogger(__name__)


def compute_precision_recall_at_k(
    *,
    retrieved_doc_ids: list[str],
    relevant_doc_ids: list[str],
    k: int,
) -> tuple[float, float]:
    """Doc-level Precision@k and Recall@k."""
    retrieved = [d for d in retrieved_doc_ids if d][: max(k, 0)]
    relevant = {d for d in relevant_doc_ids if d}
    if not retrieved and not relevant:
        return 1.0, 1.0
    if not retrieved:
        return 0.0, 0.0 if relevant else 1.0
    hit = len(set(retrieved) & relevant)
    precision = hit / len(retrieved)
    recall = (hit / len(relevant)) if relevant else (1.0 if hit == 0 else 0.0)
    if not relevant:
        return precision, 0.0
    return precision, recall


def _evidence_item_to_eval_item(item: EvidenceItem) -> dict[str, Any]:
    meta = item.metadata or {}
    return {
        "id": item.id,
        "title": item.title or "",
        "snippet": item.snippet or "",
        "score": item.score,
        "citable_as": item.citable_as or "",
        "kind": item.kind or "general",
        "doc_id": meta.get("doc_id"),
        "space_id": meta.get("space_id"),
        "heading_path": meta.get("heading_path"),
        "page_no": meta.get("page_no"),
        "block": meta.get("block") or "text",
        "source_filename": meta.get("source_filename"),
        "doc_title": meta.get("doc_title"),
    }


def _eval_case_from_pack(
    *,
    q: str,
    needles: list[str],
    relevant_doc_ids: list[str],
    pack: EvidencePackResponse,
    top_k: int,
) -> dict[str, Any]:
    items = [_evidence_item_to_eval_item(it) for it in pack.items]
    retrieved_docs: list[str] = []
    for item in items:
        did = item.get("doc_id")
        if did and str(did) not in retrieved_docs:
            retrieved_docs.append(str(did))
    blob = "\n".join(str(item.get("snippet") or "") for item in items)
    needle_ok = (not needles) or any(n in blob for n in needles)
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    if relevant_doc_ids:
        precision_at_k, recall_at_k = compute_precision_recall_at_k(
            retrieved_doc_ids=retrieved_docs,
            relevant_doc_ids=relevant_doc_ids,
            k=top_k,
        )
    return {
        "q": q,
        "hits": len(items),
        "items": items,
        "retrieved_doc_ids": retrieved_docs,
        "relevant_doc_ids": relevant_doc_ids,
        "needle_hit": needle_ok,
        "precision_at_k": precision_at_k,
        "recall_at_k": recall_at_k,
        "top_score": items[0].get("score") if items else None,
    }


def _summarize_eval_cases(cases: list[dict[str, Any]], *, top_k: int) -> dict[str, Any]:
    precisions: list[float] = []
    recalls: list[float] = []
    needle_hits = 0
    labeled = 0
    for case in cases:
        needle_hits += int(bool(case.get("needle_hit")))
        if case.get("relevant_doc_ids"):
            labeled += 1
            if case.get("precision_at_k") is not None:
                precisions.append(float(case["precision_at_k"]))
            if case.get("recall_at_k") is not None:
                recalls.append(float(case["recall_at_k"]))
    n = max(len(cases), 1)
    return {
        "top_k": top_k,
        "case_count": len(cases),
        "needle_hit_rate": needle_hits / n,
        "precision_at_k": (sum(precisions) / len(precisions)) if precisions else None,
        "recall_at_k": (sum(recalls) / len(recalls)) if recalls else None,
        "labeled_case_count": labeled,
        "cases": cases,
    }


def _resolve_search_space_ids(spaces: list[str] | None, allowed_ids: set[str]) -> list[str]:
    """Resolve caller space ids against ACL.

    - ``None``: all accessible spaces (direct API / explicit session widen)
    - ``[]``: no spaces (unbound agent or session disabled)
    - non-empty list: intersection with ACL
    """
    if spaces is None:
        return list(allowed_ids)
    if not spaces:
        return []
    return [s for s in spaces if s in allowed_ids]


async def eval_recall(
    session: AsyncSession,
    *,
    user_id: str,
    system_role: str,
    spaces: list[str] | None,
    cases: list[RecallEvalCase],
    top_k: int = 5,
    scenario: str | None = None,
    knowledge_version: str = "current",
    similarity_cutoff: float | None = None,
    as_of_date: str | None = None,
) -> RecallEvalResponse:
    """Run Precision@k / Recall@k / needle eval via the same retrieval path as ``search()``."""
    accessible = await list_accessible_spaces(session, user_id=user_id, system_role=system_role)
    allowed_ids = {s.id for s in accessible}
    if _resolve_search_space_ids(spaces, allowed_ids) == []:
        raise HTTPException(status_code=403, detail="No accessible spaces for eval")

    per_case: list[dict[str, Any]] = []
    for case in cases:
        q = case.q.strip()
        if not q:
            continue
        pack = await search(
            session,
            user_id=user_id,
            system_role=system_role,
            query=q,
            spaces=spaces,
            top_k=top_k,
            similarity_cutoff=similarity_cutoff,
            knowledge_version=knowledge_version,
            scenario=scenario,
            as_of_date=as_of_date,
        )
        per_case.append(
            _eval_case_from_pack(
                q=q,
                needles=[str(n) for n in case.needles if n],
                relevant_doc_ids=[str(d) for d in case.relevant_doc_ids if d],
                pack=pack,
                top_k=top_k,
            )
        )

    result = _summarize_eval_cases(per_case, top_k=top_k)
    return RecallEvalResponse(
        top_k=result["top_k"],
        case_count=result["case_count"],
        needle_hit_rate=float(result["needle_hit_rate"]),
        precision_at_k=result.get("precision_at_k"),
        recall_at_k=result.get("recall_at_k"),
        labeled_case_count=int(result.get("labeled_case_count") or 0),
        cases=list(result.get("cases") or []),
        trace_id=str(uuid.uuid4()),
    )


def attach_user_attrs(items: list[EvidenceItem]) -> None:

    for it in items:
        attrs = user_attrs_from_metadata(it.metadata)
        it.attrs = attrs or None


def _enrich_evidence_items(
    items: list[EvidenceItem],
    *,
    pack_id: str,
    space_ids: list[str],
    doc_meta: dict[str, KnowledgeDocumentRow],
) -> None:
    for it in items:
        it.metadata = dict(it.metadata or {})
        it.metadata.setdefault("scenario", pack_id)
        it.metadata.setdefault("spaces_searched", space_ids)
        row = doc_meta.get(str(it.metadata.get("doc_id") or ""))
        if row is None:
            continue
        it.metadata["source_filename"] = row.source_filename
        it.metadata["doc_title"] = row.title
        attrs = row.attrs if isinstance(row.attrs, dict) else {}
        for key, value in attrs.items():
            if key.startswith("_"):
                continue
            if key == "enabled":
                it.metadata["enabled"] = value
            else:
                it.metadata.setdefault(key, value)
        if row.effective_from is not None:
            it.metadata["effective_from"] = row.effective_from.isoformat()
        if row.effective_to is not None:
            it.metadata["effective_to"] = row.effective_to.isoformat()
        if not it.title:
            it.title = row.title
        if not it.citable_as:
            heading = it.metadata.get("heading_path")
            article = it.metadata.get("article_no")
            base = f"{row.title} / {article}".strip(" /") if article else row.title
            it.citable_as = f"{base} / {heading}".strip(" /") if heading else base


async def search(
    session: AsyncSession,
    *,
    user_id: str,
    system_role: str,
    query: str,
    spaces: list[str] | None,
    top_k: int | None,
    retrieve_top_k: int | None = None,
    similarity_cutoff: float | None = None,
    knowledge_version: str = "current",
    scenario: str | None = None,
    as_of_date: str | None = None,
    fusion_queries: int | None = None,
) -> EvidencePackResponse:
    from fastapi import HTTPException

    if not query.strip():
        raise HTTPException(status_code=422, detail="query required")

    spaces, scenario = resolve_agent_knowledge_scope(spaces, scenario)
    accessible = await list_accessible_spaces(session, user_id=user_id, system_role=system_role)
    allowed_ids = {s.id for s in accessible}
    accessible_by_id = {s.id: s for s in accessible}
    space_ids = _resolve_search_space_ids(spaces, allowed_ids)

    trace_id = str(uuid.uuid4())
    if not space_ids:
        return EvidencePackResponse(
            knowledge_version=knowledge_version,
            trace_id=trace_id,
            items=[],
            answer=None,
        )

    default_scenarios: list[str] = []
    for sid in space_ids:
        sp = accessible_by_id.get(sid)
        if sp and sp.default_scenarios:
            default_scenarios = list(sp.default_scenarios)
            break
    pack = resolve_scenario(request_scenario=scenario, space_default_scenarios=default_scenarios)
    scenario_cfg = get_scenario_config(pack.id)
    space_top_k: int | None = None
    space_score: float | None = None
    if space_ids:
        primary = accessible_by_id.get(space_ids[0])
        if primary is not None:
            space_top_k, space_score = space_retrieval_from_row(primary)
    effective_top_k = top_k if top_k is not None else space_top_k if space_top_k is not None else pack.top_k
    final_top_k = int(effective_top_k or scenario_cfg.top_k or 8)
    pool_k = retrieve_top_k if retrieve_top_k is not None else effective_top_k
    per_space_pool = max(1, int(pool_k or final_top_k))
    cutoff = similarity_cutoff if similarity_cutoff is not None else (space_score if space_score is not None else pack.score)
    if fusion_queries is None and scenario_cfg.fusion_num_queries is not None:
        fusion_queries = max(1, int(scenario_cfg.fusion_num_queries))

    ver_label = (knowledge_version or "current").strip() or "current"
    release_by_space = {sid: space_knowledge_version(accessible_by_id.get(sid)) if ver_label == "current" else ver_label for sid in space_ids}
    resolved_version = ver_label if ver_label != "current" else next(iter(release_by_space.values()), "current")
    merge_mode = str(scenario_cfg.merge_mode or "slot_then_rrf")

    async def _search_one(space_id: str) -> tuple[str, list[dict]]:
        release = release_by_space.get(space_id, "current")
        items = await asyncio.to_thread(
            retrieve_in_space,
            space_id=space_id,
            query=query,
            top_k=per_space_pool,
            similarity_cutoff=cutoff,
            release=release,
            fusion_queries=fusion_queries,
            merge_mode=merge_mode,
        )
        return space_id, items

    if len(space_ids) == 1:
        _sid, raw = await _search_one(space_ids[0])
        space_results = [{"space_id": _sid, "hit_count": len(raw)}]
    else:
        pairs = await asyncio.gather(*[_search_one(sid) for sid in space_ids])
        budgets = space_budgets(len(space_ids), final_top_k)
        buckets = [(sid, items, budget) for (sid, items), budget in zip(pairs, budgets)]
        raw = merge_space_hits(buckets, final_top_k=final_top_k, merge_mode=merge_mode)
        space_results = [{"space_id": sid, "hit_count": len(items)} for sid, items in pairs]

    as_of_dt = parse_as_of(as_of_date)
    doc_ids = {str(x.get("metadata", {}).get("doc_id")) for x in raw if x.get("metadata", {}).get("doc_id")}
    doc_meta: dict[str, KnowledgeDocumentRow] = {}
    if doc_ids:
        rows = (await session.execute(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id.in_(doc_ids)))).scalars().all()
        doc_meta = {r.id: r for r in rows}
    raw = filter_hits_by_document_state(raw, doc_meta, as_of=as_of_dt)
    raw = rank_by_temporal(raw, query=query, as_of=as_of_dt)
    raw = stable_rank_items(raw)[:final_top_k]
    items = [EvidenceItem.model_validate(x) for x in raw]
    _enrich_evidence_items(
        items,
        pack_id=pack.id,
        space_ids=space_ids,
        doc_meta=doc_meta,
    )
    attach_user_attrs(items)
    extra: dict[str, Any] = {}
    if len(space_ids) > 1:
        extra["metadata"] = {
            "spaces": list(space_ids),
            "merge_mode": merge_mode,
            "space_results": space_results,
        }
    return EvidencePackResponse(
        knowledge_version=resolved_version,
        trace_id=trace_id,
        items=items,
        **extra,
    )
