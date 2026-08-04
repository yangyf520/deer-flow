"""Knowledge catalog backed by ``pub_codes`` (user-managed 码表)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.config.knowledge_config import (
    KnowledgeConfig,
    KnowledgeScenarioConfig,
    KnowledgeTagGroupConfig,
    ScenarioLaneConfig,
    get_knowledge_config,
)
from deerflow.persistence.pub_codes.model import PubCodeRow

KNOWLEDGE_DOMAIN = "knowledge"
TYPE_SCENARIO = "scenario"
TYPE_KIND = "kind"
TYPE_TAG = "tag"
TYPE_TAG_GROUP = "tag_group"
LOCALE_ZH = "zh-CN"
LOCALE_EN = "en-US"

# Default industry scenario catalog (code, zh label, en label).
CANONICAL_SCENARIOS: tuple[tuple[str, str, str], ...] = (
    ("auto", "自动驾驶", "Autonomous driving"),
    ("health", "智慧医疗", "Smart healthcare"),
    ("fintech", "金融科技", "FinTech"),
    ("smart-city", "智慧城市", "Smart city"),
    ("education", "教育", "Education"),
    ("business", "商业", "Business"),
    ("culture-media", "文娱", "Culture & entertainment"),
)

CANONICAL_SCENARIO_CODES: frozenset[str] = frozenset(code for code, _, _ in CANONICAL_SCENARIOS)


def default_scenario_code() -> str:
    return CANONICAL_SCENARIOS[0][0]


_cache_lock = threading.Lock()
_catalog_cache: _CatalogCache | None = None


@dataclass
class _CatalogCache:
    scenarios: dict[str, KnowledgeScenarioConfig] = field(default_factory=dict)
    scenario_labels: dict[str, str] = field(default_factory=dict)
    scenario_space_ids: dict[str, str] = field(default_factory=dict)
    scenario_host_space_ids: dict[str, str] = field(default_factory=dict)
    # scenario_code -> list of kind codes
    kinds_by_scenario: dict[str, list[str]] = field(default_factory=dict)
    kind_labels: dict[str, str] = field(default_factory=dict)
    i18n_labels: dict[str, dict[str, str]] = field(default_factory=dict)
    tags_by_scenario: dict[str, dict[str, str]] = field(default_factory=dict)
    # (scenario_code, group_code) -> {label, tags}
    tag_groups: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def invalidate_cache() -> None:
    global _catalog_cache
    with _cache_lock:
        _catalog_cache = None


def cached_scenario(scenario_id: str | None) -> KnowledgeScenarioConfig | None:
    """Sync read for RAG — populated by ``refresh_cache``."""
    sid = (scenario_id or "").strip()
    if not sid:
        return None
    with _cache_lock:
        if _catalog_cache is None:
            return None
        return _catalog_cache.scenarios.get(sid)


def cached_scenario_codes() -> set[str]:
    with _cache_lock:
        if _catalog_cache is None:
            return set()
        return set(_catalog_cache.scenarios.keys())


def _scenario_config_from_row(row: PubCodeRow) -> KnowledgeScenarioConfig:
    attrs = dict(row.attrs or {})
    attrs.pop("labels", None)
    attrs.pop("space_id", None)
    attrs.pop("host_space_id", None)
    attrs.pop("top_k", None)
    attrs.pop("score", None)
    lanes_raw = attrs.pop("lanes", None) or []
    kinds_raw = attrs.pop("kinds", None) or []
    lanes = [ScenarioLaneConfig.model_validate(lane) for lane in lanes_raw if isinstance(lane, dict)]
    return KnowledgeScenarioConfig(
        type=row.code,
        description=str(attrs.pop("description", "") or ""),
        merge_mode=str(attrs.pop("merge_mode", "slot_then_rrf") or "slot_then_rrf"),
        fusion_num_queries=attrs.pop("fusion_num_queries", None),
        kinds=[str(k) for k in kinds_raw if k],
        lanes=lanes,
    )


def _build_cache(rows: list[PubCodeRow]) -> _CatalogCache:
    cache = _CatalogCache()
    for row in rows:
        if not row.enabled:
            continue
        if row.domain != KNOWLEDGE_DOMAIN:
            continue
        if row.type_key == TYPE_SCENARIO:
            cache.scenarios[row.code] = _scenario_config_from_row(row)
            labels = _labels_from_row(row)
            cache.i18n_labels[row.code] = labels
            cache.scenario_labels[row.code] = _main_label(labels) or row.code
            row_attrs = row.attrs if isinstance(row.attrs, dict) else None
            cache.scenario_space_ids[row.code] = linked_scenario_space_id(
                row.code,
                row_attrs,
            )
            host = catalog_host_space_id(row_attrs)
            if host:
                cache.scenario_host_space_ids[row.code] = host
        elif row.type_key == TYPE_KIND and row.parent_code:
            cache.kinds_by_scenario.setdefault(row.parent_code, []).append(row.code)
            cache.kind_labels[row.code] = row.label or row.code
        elif row.type_key == TYPE_TAG and row.parent_code:
            cache.tags_by_scenario.setdefault(row.parent_code, {})[row.code] = row.label or row.code
        elif row.type_key == TYPE_TAG_GROUP and row.parent_code:
            tags = [str(t) for t in (row.attrs or {}).get("tags", []) if t]
            cache.tag_groups[(row.parent_code, row.code)] = {
                "label": row.label or row.code,
                "tags": tags,
            }
    for scenario, kinds in cache.kinds_by_scenario.items():
        cache.kinds_by_scenario[scenario] = sorted(set(kinds))
    return cache


def _apply_cache(cache: _CatalogCache) -> None:
    global _catalog_cache
    with _cache_lock:
        _catalog_cache = cache


async def refresh_cache(session: AsyncSession) -> _CatalogCache:
    rows = list((await session.execute(select(PubCodeRow).where(PubCodeRow.domain == KNOWLEDGE_DOMAIN).order_by(PubCodeRow.sort_order, PubCodeRow.code))).scalars().all())
    cache = _build_cache(rows)
    _apply_cache(cache)
    return cache


def _default_label_for_code(code: str) -> str:
    return code.replace("-", " ").replace("_", " ")


def _norm_labels(
    labels: dict[str, str] | None,
    *,
    fallback_label: str = "",
) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (labels or {}).items():
        text = str(value or "").strip()
        if text:
            out[str(key).strip()] = text
    fb = (fallback_label or "").strip()
    if fb:
        if LOCALE_ZH not in out:
            out[LOCALE_ZH] = fb
        if LOCALE_EN not in out:
            out[LOCALE_EN] = fb
    return out


def _labels_from_row(row: PubCodeRow) -> dict[str, str]:
    stored = (row.attrs or {}).get("labels")
    if isinstance(stored, dict):
        normalized = _norm_labels({str(k): str(v) for k, v in stored.items()})
        if normalized:
            return normalized
    fb = (row.label or row.code or "").strip()
    return _norm_labels(None, fallback_label=fb)


def _main_label(labels: dict[str, str]) -> str:
    return labels.get(LOCALE_ZH) or labels.get(LOCALE_EN) or next(iter(labels.values()), "")


def linked_scenario_space_id(code: str, attrs: dict[str, Any] | None = None) -> str:
    """Knowledge space id bound to a scenario — defaults to scenario code."""
    raw = str((attrs or {}).get("space_id") or "").strip()
    sid = (code or "").strip()
    return raw or sid


def catalog_host_space_id(attrs: dict[str, Any] | None = None) -> str:
    """Knowledge space that owns this scenario in the catalog (码表归属)."""
    return str((attrs or {}).get("host_space_id") or "").strip()


def _compact_scenario_attrs(attrs: dict[str, Any], *, code: str) -> dict[str, Any]:
    """Drop redundant / default scenario attrs before persisting."""
    out: dict[str, Any] = {}
    sid = (code or "").strip()

    description = str(attrs.get("description") or "").strip()
    if description:
        out["description"] = description

    fusion = attrs.get("fusion_num_queries")
    if fusion is not None:
        out["fusion_num_queries"] = fusion

    merge_mode = str(attrs.get("merge_mode") or "").strip()
    if merge_mode and merge_mode != "slot_then_rrf":
        out["merge_mode"] = merge_mode

    lanes = attrs.get("lanes") or []
    kinds = attrs.get("kinds") or []
    if lanes:
        out["lanes"] = lanes
    elif kinds:
        out["kinds"] = kinds

    labels = attrs.get("labels")
    if isinstance(labels, dict) and labels:
        out["labels"] = labels

    space_id = linked_scenario_space_id(sid, attrs)
    if space_id != sid:
        out["space_id"] = space_id

    host_space_id = catalog_host_space_id(attrs)
    if host_space_id:
        out["host_space_id"] = host_space_id

    return out


def _scenario_attrs_payload(
    *,
    code: str,
    normalized_labels: dict[str, str],
    description: str = "",
    merge_mode: str = "slot_then_rrf",
    fusion_num_queries: int | None = None,
    kinds: list[str] | None = None,
    lanes: list[dict[str, Any]] | None = None,
    space_id: str | None = None,
    host_space_id: str | None = None,
) -> dict[str, Any]:
    lane_list = list(lanes or [])
    kind_list = list(kinds or [])
    raw: dict[str, Any] = {"labels": normalized_labels}
    if description.strip():
        raw["description"] = description.strip()
    if merge_mode and merge_mode != "slot_then_rrf":
        raw["merge_mode"] = merge_mode
    if fusion_num_queries is not None:
        raw["fusion_num_queries"] = fusion_num_queries
    if lane_list:
        raw["lanes"] = lane_list
    elif kind_list:
        raw["kinds"] = kind_list
    linked = (space_id or "").strip()
    if linked and linked != code:
        raw["space_id"] = linked
    host = (host_space_id or "").strip()
    if host:
        raw["host_space_id"] = host
    return _compact_scenario_attrs(raw, code=code)


def norm_locale(value: str | None) -> str:
    raw = (value or "").strip()
    if raw in (LOCALE_ZH, LOCALE_EN):
        return raw
    lower = raw.lower()
    if lower.startswith("zh"):
        return LOCALE_ZH
    if lower.startswith("en"):
        return LOCALE_EN
    return LOCALE_ZH


def locale_from_header(header: str | None) -> str:
    if not header:
        return LOCALE_ZH
    first = header.split(",")[0].strip().split(";")[0].strip()
    return norm_locale(first)


def pick_label(labels: dict[str, str], locale: str, *, fallback: str = "") -> str:
    """Pick display label for API responses — locale first, then fallbacks."""
    for key in (norm_locale(locale), LOCALE_ZH, LOCALE_EN):
        text = (labels.get(key) or "").strip()
        if text:
            return text
    return fallback


def _scenario_lane_tags(scenario: KnowledgeScenarioConfig) -> set[str]:
    tags: set[str] = set()
    for lane in scenario.lanes or []:
        tags.update(str(tag) for tag in (lane.tags or []) if tag)
    return tags


def _tag_group_fits(
    scenario: KnowledgeScenarioConfig,
    group: KnowledgeTagGroupConfig,
) -> bool:
    """Tag groups are scenario-scoped 码表 entries — only when lanes use those tags."""
    scenario_tags = _scenario_lane_tags(scenario)
    if not scenario_tags:
        return False
    group_tags = {str(tag) for tag in (group.tags or []) if tag}
    return bool(group_tags.intersection(scenario_tags))


def _seed_defaults() -> KnowledgeConfig:
    """Bootstrap catalog when DB and config.yaml both omit scenarios."""
    return KnowledgeConfig(
        scenarios=[KnowledgeScenarioConfig(type=code) for code, _, _ in CANONICAL_SCENARIOS],
        tag_groups=[],
    )


async def seed_catalog(session: AsyncSession) -> bool:
    """One-time bootstrap: copy config.yaml catalog into pub_codes when empty."""
    existing = (await session.execute(select(PubCodeRow.id).where(PubCodeRow.domain == KNOWLEDGE_DOMAIN, PubCodeRow.type_key == TYPE_SCENARIO).limit(1))).scalar_one_or_none()
    if existing:
        return False

    cfg = get_knowledge_config()
    if not cfg.scenarios:
        cfg = _seed_defaults()
    now = _utcnow()
    rows: list[PubCodeRow] = []

    kind_labels = {k.id: _default_label_for_code(k.id) for k in cfg.kinds if k.id}
    tag_labels = {t.id: _default_label_for_code(t.id) for t in cfg.tags if t.id}
    tag_group_defs = list(cfg.tag_groups)

    label_map = {code: zh for code, zh, _ in CANONICAL_SCENARIOS}
    label_map.update(
        {
            "policy": "制度",
            "reference": "法规",
            "case": "案例",
            "national": "国家法规",
            "company": "公司制度",
            "statute": "法律",
            "national-law": "国家法律",
            "company-policy": "公司制度",
        }
    )
    english_label_map = {code: en for code, _, en in CANONICAL_SCENARIOS}

    for index, scenario in enumerate(cfg.scenarios):
        label_zh = label_map.get(scenario.type, _default_label_for_code(scenario.type))
        label_en = english_label_map.get(scenario.type, _default_label_for_code(scenario.type))
        scenario_labels = _norm_labels(
            {LOCALE_ZH: label_zh, LOCALE_EN: label_en},
        )
        attrs: dict[str, Any] = {
            "labels": scenario_labels,
        }
        if scenario.description:
            attrs["description"] = scenario.description
        if scenario.merge_mode and scenario.merge_mode != "slot_then_rrf":
            attrs["merge_mode"] = scenario.merge_mode
        if scenario.fusion_num_queries is not None:
            attrs["fusion_num_queries"] = scenario.fusion_num_queries
        lane_payload = [lane.model_dump(exclude_none=True) for lane in (scenario.lanes or [])]
        if lane_payload:
            attrs["lanes"] = lane_payload
        elif scenario.kinds:
            attrs["kinds"] = list(scenario.kinds)
        attrs = _compact_scenario_attrs(attrs, code=scenario.type)
        rows.append(
            PubCodeRow(
                id=str(uuid.uuid4()),
                domain=KNOWLEDGE_DOMAIN,
                type_key=TYPE_SCENARIO,
                code=scenario.type,
                label=_main_label(scenario_labels),
                parent_code="",
                attrs=attrs,
                sort_order=index,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        scenario_kinds: set[str] = set(scenario.kinds or [])
        for lane in scenario.lanes or []:
            scenario_kinds.update(k for k in (lane.kinds or []) if k)
        for kind_index, kind in enumerate(sorted(scenario_kinds)):
            rows.append(
                PubCodeRow(
                    id=str(uuid.uuid4()),
                    domain=KNOWLEDGE_DOMAIN,
                    type_key=TYPE_KIND,
                    code=kind,
                    label=label_map.get(kind, kind_labels.get(kind, _default_label_for_code(kind))),
                    parent_code=scenario.type,
                    attrs={},
                    sort_order=kind_index,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            )

    if tag_group_defs:
        for scenario in cfg.scenarios:
            applicable = [group for group in tag_group_defs if group.id and _tag_group_fits(scenario, group)]
            for group_index, group in enumerate(applicable):
                rows.append(
                    PubCodeRow(
                        id=str(uuid.uuid4()),
                        domain=KNOWLEDGE_DOMAIN,
                        type_key=TYPE_TAG_GROUP,
                        code=group.id,
                        label=label_map.get(group.id, _default_label_for_code(group.id)),
                        parent_code=scenario.type,
                        attrs={"tags": list(group.tags or [])},
                        sort_order=group_index,
                        enabled=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
                for tag in group.tags or []:
                    if tag in tag_labels:
                        continue
                    tag_labels[tag] = _default_label_for_code(tag)

    seen_tags: set[tuple[str, str]] = set()
    for scenario in cfg.scenarios:
        for lane in scenario.lanes or []:
            for tag in lane.tags or []:
                key = (scenario.type, str(tag))
                if key in seen_tags:
                    continue
                seen_tags.add(key)
                rows.append(
                    PubCodeRow(
                        id=str(uuid.uuid4()),
                        domain=KNOWLEDGE_DOMAIN,
                        type_key=TYPE_TAG,
                        code=str(tag),
                        label=label_map.get(str(tag), tag_labels.get(str(tag), _default_label_for_code(str(tag)))),
                        parent_code=scenario.type,
                        attrs={},
                        sort_order=0,
                        enabled=True,
                        created_at=now,
                        updated_at=now,
                    )
                )

    for row in rows:
        session.add(row)
    if rows:
        await session.commit()
    return bool(rows)


async def repair_tag_groups(session: AsyncSession) -> int:
    """Drop tag_group rows not referenced by the parent scenario's lane tags."""
    rows = list(
        (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                    PubCodeRow.type_key == TYPE_TAG_GROUP,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    scenario_rows = {
        row.code: row
        for row in (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                    PubCodeRow.type_key == TYPE_SCENARIO,
                    PubCodeRow.parent_code == "",
                )
            )
        )
        .scalars()
        .all()
    }

    removed = 0
    for row in rows:
        parent = (row.parent_code or "").strip()
        scenario_row = scenario_rows.get(parent)
        if scenario_row is None:
            await session.delete(row)
            removed += 1
            continue
        scenario_cfg = _scenario_config_from_row(scenario_row)
        scenario_tags = _scenario_lane_tags(scenario_cfg)
        group_tags = {str(tag) for tag in (row.attrs or {}).get("tags", []) if tag}
        if not scenario_tags or not group_tags.intersection(scenario_tags):
            await session.delete(row)
            removed += 1

    if removed:
        await session.commit()
    return removed


async def sync_canonical_scenarios(session: AsyncSession) -> int:
    """Upsert default industry scenarios and hide legacy bootstrap rows."""
    changed = 0
    now = _utcnow()
    for index, (code, label_zh, label_en) in enumerate(CANONICAL_SCENARIOS):
        labels = _norm_labels({LOCALE_ZH: label_zh, LOCALE_EN: label_en})
        attrs = _compact_scenario_attrs({"labels": labels}, code=code)
        display = _main_label(labels)
        row = (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                    PubCodeRow.type_key == TYPE_SCENARIO,
                    PubCodeRow.parent_code == "",
                    PubCodeRow.code == code,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(
                PubCodeRow(
                    id=str(uuid.uuid4()),
                    domain=KNOWLEDGE_DOMAIN,
                    type_key=TYPE_SCENARIO,
                    code=code,
                    label=display,
                    parent_code="",
                    attrs=attrs,
                    sort_order=index,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed += 1
            continue
        dirty = False
        if row.label != display:
            row.label = display
            dirty = True
        if row.attrs != attrs:
            row.attrs = attrs
            dirty = True
        if row.sort_order != index:
            row.sort_order = index
            dirty = True
        if not row.enabled:
            row.enabled = True
            dirty = True
        if dirty:
            row.updated_at = now
            changed += 1

    legacy_rows = list(
        (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                    PubCodeRow.type_key == TYPE_SCENARIO,
                    PubCodeRow.parent_code == "",
                )
            )
        )
        .scalars()
        .all()
    )
    for row in legacy_rows:
        if row.code in CANONICAL_SCENARIO_CODES or not row.enabled:
            continue
        row.enabled = False
        row.updated_at = now
        changed += 1

    if changed:
        await session.commit()
    return changed


async def repair_scenario_attrs(session: AsyncSession) -> int:
    """Normalize stored scenario attrs (drop redundant keys from older rows)."""
    rows = list(
        (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                    PubCodeRow.type_key == TYPE_SCENARIO,
                    PubCodeRow.parent_code == "",
                )
            )
        )
        .scalars()
        .all()
    )
    updated = 0
    for row in rows:
        compact = _compact_scenario_attrs(dict(row.attrs or {}), code=row.code)
        if compact != (row.attrs or {}):
            row.attrs = compact
            row.updated_at = _utcnow()
            updated += 1
    if updated:
        await session.commit()
    return updated


async def ensure_catalog(session: AsyncSession) -> _CatalogCache:
    await seed_catalog(session)
    await sync_canonical_scenarios(session)
    await repair_tag_groups(session)
    await repair_scenario_attrs(session)
    return await refresh_cache(session)


async def list_scenario_codes(session: AsyncSession) -> list[str]:
    cache = await ensure_catalog(session)
    return sorted(cache.scenarios.keys())


async def validate_scenario_code(session: AsyncSession, code: str) -> str:
    from fastapi import HTTPException

    want = (code or "").strip()
    if not want:
        raise HTTPException(status_code=422, detail="scenario is required")
    cache = await ensure_catalog(session)
    if want not in cache.scenarios:
        known = sorted(cache.scenarios.keys())
        raise HTTPException(
            status_code=422,
            detail=f"unknown scenario type {want!r}; configured: {known}",
        )
    return want


def build_catalog(cache: _CatalogCache, *, locale: str = LOCALE_ZH) -> dict[str, Any]:
    """Build API catalog dict from in-memory cache."""
    from deerflow.knowledge.rag import scenario_kind_ids

    loc = norm_locale(locale)

    scenarios_out: list[dict[str, Any]] = []
    kinds_out: list[dict[str, Any]] = []
    tags_out: list[dict[str, Any]] = []
    tag_groups_out: list[dict[str, Any]] = []
    seen_kinds: set[str] = set()

    for code, cfg in sorted(cache.scenarios.items()):
        scenarios_out.append(
            {
                "description": cfg.description,
                "type": code,
                "label": pick_label(
                    cache.i18n_labels.get(code, {}),
                    loc,
                    fallback=code,
                ),
                "space_id": cache.scenario_space_ids.get(code, code),
                "host_space_id": cache.scenario_host_space_ids.get(code, ""),
                "kinds": scenario_kind_ids(cfg),
                "lanes": [
                    {
                        "id": lane.id,
                        "kinds": list(lane.kinds or []),
                        "tags": list(lane.tags or []),
                        "budget": lane.budget,
                        "optional": bool(lane.optional),
                    }
                    for lane in (cfg.lanes or [])
                ],
            }
        )
        for kind in cache.kinds_by_scenario.get(code, []):
            if kind not in seen_kinds:
                seen_kinds.add(kind)
                kinds_out.append({"id": kind, "label": cache.kind_labels.get(kind, kind)})
        for (scenario_code, group_code), meta in sorted(cache.tag_groups.items()):
            if scenario_code != code:
                continue
            tag_groups_out.append(
                {
                    "id": group_code,
                    "label": meta.get("label", group_code),
                    "tags": list(meta.get("tags") or []),
                    "scenario": scenario_code,
                }
            )
        for tag_code, label in sorted(cache.tags_by_scenario.get(code, {}).items()):
            tags_out.append({"id": tag_code, "label": label, "scenario": code})

    return {
        "kinds": kinds_out,
        "tags": tags_out,
        "tag_groups": tag_groups_out,
        "scenarios": scenarios_out,
    }


async def get_catalog(session: AsyncSession, *, locale: str = LOCALE_ZH) -> dict[str, Any]:
    cache = await ensure_catalog(session)
    return build_catalog(cache, locale=locale)


async def upsert_scenario(
    session: AsyncSession,
    *,
    code: str,
    label: str,
    locale: str | None = None,
    labels: dict[str, str] | None = None,
    description: str = "",
    merge_mode: str = "slot_then_rrf",
    fusion_num_queries: int | None = None,
    kinds: list[str] | None = None,
    lanes: list[dict[str, Any]] | None = None,
    host_space_id: str | None = None,
    created_by: str | None = None,
) -> PubCodeRow:
    """Create or update a knowledge scenario definition."""
    sid = (code or "").strip()
    if not sid:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="scenario code is required")

    row = (
        await session.execute(
            select(PubCodeRow).where(
                PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                PubCodeRow.type_key == TYPE_SCENARIO,
                PubCodeRow.parent_code == "",
                PubCodeRow.code == sid,
            )
        )
    ).scalar_one_or_none()

    loc = norm_locale(locale)
    existing_labels = _labels_from_row(row) if row is not None else {}
    if labels:
        normalized_labels = _norm_labels(labels, fallback_label=label)
    else:
        normalized_labels = dict(existing_labels)
        text = (label or "").strip()
        if text:
            normalized_labels[loc] = text
    if not normalized_labels:
        normalized_labels = _norm_labels(None, fallback_label=label or sid)

    existing_space_id = ""
    existing_host_space_id = ""
    if row is not None:
        row_attrs = row.attrs if isinstance(row.attrs, dict) else None
        existing_space_id = linked_scenario_space_id(sid, row_attrs)
        if existing_space_id == sid:
            existing_space_id = ""
        existing_host_space_id = catalog_host_space_id(row_attrs)

    resolved_host = (host_space_id or "").strip() or existing_host_space_id or None

    attrs = _scenario_attrs_payload(
        code=sid,
        normalized_labels=normalized_labels,
        description=description,
        merge_mode=merge_mode,
        fusion_num_queries=fusion_num_queries,
        kinds=kinds,
        lanes=lanes,
        space_id=existing_space_id or None,
        host_space_id=resolved_host,
    )
    display_label = pick_label(normalized_labels, loc, fallback=sid)
    now = _utcnow()
    if row is None:
        row = PubCodeRow(
            id=str(uuid.uuid4()),
            domain=KNOWLEDGE_DOMAIN,
            type_key=TYPE_SCENARIO,
            code=sid,
            label=display_label,
            parent_code="",
            attrs=attrs,
            sort_order=0,
            enabled=True,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.label = display_label
        row.attrs = attrs
        row.updated_at = now
    await session.commit()
    await refresh_cache(session)
    return row


async def migrate_catalog_host(session: AsyncSession, *, host_space_id: str) -> int:
    """Assign all enabled catalog scenarios to a knowledge space (码表归属迁移)."""
    from fastapi import HTTPException

    target = (host_space_id or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="host_space_id is required")

    rows = list(
        (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                    PubCodeRow.type_key == TYPE_SCENARIO,
                    PubCodeRow.parent_code == "",
                    PubCodeRow.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    updated = 0
    for row in rows:
        attrs = dict(row.attrs or {})
        if catalog_host_space_id(attrs) == target:
            continue
        attrs["host_space_id"] = target
        row.attrs = _compact_scenario_attrs(attrs, code=row.code)
        row.updated_at = _utcnow()
        updated += 1
    if updated:
        await session.commit()
        await refresh_cache(session)
    return updated


async def delete_scenario(session: AsyncSession, code: str) -> tuple[bool, str | None]:
    """Delete scenario row and children. Returns (deleted, linked space_id)."""
    sid = (code or "").strip()
    scenario = (
        await session.execute(
            select(PubCodeRow).where(
                PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                PubCodeRow.type_key == TYPE_SCENARIO,
                PubCodeRow.parent_code == "",
                PubCodeRow.code == sid,
            )
        )
    ).scalar_one_or_none()
    if scenario is None:
        return False, None
    space_id = linked_scenario_space_id(sid, scenario.attrs if isinstance(scenario.attrs, dict) else None)
    children = list(
        (
            await session.execute(
                select(PubCodeRow).where(
                    PubCodeRow.domain == KNOWLEDGE_DOMAIN,
                    PubCodeRow.parent_code == sid,
                )
            )
        )
        .scalars()
        .all()
    )
    await session.delete(scenario)
    for row in children:
        await session.delete(row)
    await session.commit()
    await refresh_cache(session)
    return True, space_id
