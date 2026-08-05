import type { Translations } from "@/core/i18n/locales/types";

import type { SpaceAccessValue, SpaceRoleValue } from "./api";

type KnowledgeT = Translations["knowledge"];

/** Tag group entry from knowledge catalog API. */
export type TagGroupCatalogEntry = {
  id: string;
  tags: string[];
  label?: string;
  scenario?: string;
};

export type TagGroupId = string;

export function scenarioLabel(
  scenarioType: string,
  t: KnowledgeT,
  entry?: { label?: string },
): string {
  if (entry?.label?.trim()) return entry.label.trim();
  return t.scenarios[scenarioType] ?? scenarioType;
}

export function scenarioSpaceId(scenario: {
  type: string;
  space_id?: string | null;
}): string {
  const linked = scenario.space_id?.trim();
  if (!linked) return scenario.type;
  return linked;
}

/** Catalog owner knowledge space id (码表归属). */
export function scenarioCatalogHostId(scenario: {
  host_space_id?: string | null;
}): string | null {
  const host = scenario.host_space_id?.trim();
  if (!host) return null;
  return host;
}

/** Whether a scenario belongs to the active catalog host (unassigned matches any host). */
export function scenarioMatchesCatalogHost(
  scenario: { host_space_id?: string | null },
  hostId: string | null,
): boolean {
  if (!hostId) return true;
  const host = scenarioCatalogHostId(scenario);
  if (!host) return true;
  return host === hostId;
}

export function boundScenarioType(
  space: {
    scenario?: string | null;
    default_scenarios?: string[] | null;
  } | null,
): string | null {
  if (!space) return null;
  return space.scenario ?? space.default_scenarios?.[0] ?? null;
}

/** User-facing label for a knowledge space (description first, then id). */
export function spaceDisplayLabel(space: {
  id: string;
  description?: string | null;
}): string {
  const description = space.description?.trim();
  if (description) return description;
  return space.id;
}

function isGenericSpace(id: string): boolean {
  const trimmed = id.trim();
  return (
    trimmed === "space" || trimmed === "default" || /^space-\d+$/i.test(trimmed)
  );
}

function isSpaceSlug(value: string): boolean {
  return /^[a-z0-9][a-z0-9_-]*$/i.test(value.trim());
}

/** Edit-dialog space id — recover legacy slugs stored only on name/description. */
export function spaceEditId(space: {
  id: string;
  name?: string | null;
  description?: string | null;
}): string {
  const id = space.id.trim();
  if (id && !isGenericSpace(id)) return id;
  const name = space.name?.trim();
  if (name && !isGenericSpace(name)) return name;
  const description = space.description?.trim();
  if (description && isSpaceSlug(description)) return description;
  if (id) return id;
  return name ?? "";
}

/** Card title — space code (空间编号). */
export function spaceCardTitle(space: {
  id: string;
  name?: string | null;
  description?: string | null;
}): string {
  return spaceEditId(space);
}

/** Secondary line — human description when it differs from the code title. */
export function spaceCardSubtitle(
  space: {
    id: string;
    name?: string | null;
    description?: string | null;
  },
  title: string,
): string | undefined {
  const description = space.description?.trim();
  if (description && description !== title) return description;
  const name = space.name?.trim();
  if (name && name !== title) return name;
  return undefined;
}

/** Primary space code (空间编号 / scenario code). */
export function spacePrimaryCode(space: {
  id: string;
  name?: string | null;
  scenario?: string | null;
  default_scenarios?: string[] | null;
}): string {
  const id = space.id.trim();
  const name = space.name?.trim() ?? "";
  const scenario = boundScenarioType(space);

  if (id && !isGenericSpace(id)) return id;
  if (name && /^[a-z0-9][a-z0-9_-]*$/i.test(name) && !isGenericSpace(name)) {
    return name;
  }
  if (scenario) return scenario;
  return id ? id : name ? name : "";
}

/** Human description shown beside the space code when present. */
export function spaceSecondaryDescription(
  space: { description?: string | null },
  primary: string,
): string | null {
  const description = space.description?.trim();
  if (!description || description === primary) return null;
  return description;
}

/** Machine-facing code beside the description (空间编号 or scenario code). */
export function spaceCodeLabel(space: {
  id: string;
  name?: string | null;
  description?: string | null;
  scenario?: string | null;
  default_scenarios?: string[] | null;
}): string | null {
  const code = spacePrimaryCode(space);
  return code ? code : null;
}

/** Resolve a bound space id to a user-facing label. */
export function resolveSpaceDisplayLabel(
  spaceId: string,
  spaces: {
    id: string;
    name?: string | null;
    description?: string | null;
    scenario?: string | null;
    default_scenarios?: string[] | null;
  }[],
): string {
  const match = spaces.find((s) => s.id === spaceId || s.name === spaceId);
  if (match) return spaceDisplayLabel(match);
  return spaceId;
}

export function resolveSpaceCodeLabel(
  spaceId: string,
  spaces: {
    id: string;
    name?: string | null;
    description?: string | null;
    scenario?: string | null;
    default_scenarios?: string[] | null;
  }[],
): string | null {
  const match = spaces.find((s) => s.id === spaceId || s.name === spaceId);
  if (match) return spaceCodeLabel(match);
  return isGenericSpace(spaceId) ? null : spaceId;
}

/** Default document kind for import when the UI no longer exposes kind selection. */
export function importKindForSpace(
  space: {
    allowed_kinds?: string[] | null;
    scenario?: string | null;
    default_scenarios?: string[] | null;
  } | null,
  scenarios?: { type: string; kinds?: string[] | null }[],
): string {
  const allowed = (space?.allowed_kinds ?? []).filter(Boolean);
  if (allowed.length > 0) return allowed[0]!;
  const scenarioType = boundScenarioType(space);
  const pack =
    scenarioType && scenarios
      ? scenarios.find((s) => s.type === scenarioType)
      : undefined;
  const fromScenario = (pack?.kinds ?? []).filter(Boolean);
  if (fromScenario.length > 0) return fromScenario[0]!;
  return "general";
}

export function tagLabel(tagId: string, t: KnowledgeT): string {
  return t.tags?.[tagId] ?? tagId;
}

export function tagGroupLabel(
  groupId: string,
  t: KnowledgeT,
  entry?: Pick<TagGroupCatalogEntry, "label">,
): string {
  if (entry?.label?.trim()) return entry.label.trim();
  return t.tagGroups[groupId] ?? groupId;
}

export function tagsFromTagGroups(
  groupIds: Iterable<string>,
  catalog: TagGroupCatalogEntry[],
): string[] {
  const want = new Set(groupIds);
  const out: string[] = [];
  for (const group of catalog) {
    if (!want.has(group.id)) continue;
    out.push(...group.tags);
  }
  return [...new Set(out)];
}

export function tagGroupsFromTags(
  tags: string[] | undefined,
  catalog: TagGroupCatalogEntry[],
): TagGroupId[] {
  const have = new Set(tags ?? []);
  return catalog
    .filter((g) => g.tags.some((t) => have.has(t)))
    .map((g) => g.id);
}

/** Tag groups applicable to a scenario's policy lanes (intersect lane tags with catalog). */
export function tagGroupsForScenario(
  scenario:
    | { type?: string; lanes?: { kinds?: string[]; tags?: string[] }[] | null }
    | null
    | undefined,
  catalog: TagGroupCatalogEntry[],
  kind = "policy",
): TagGroupCatalogEntry[] {
  const scenarioType = scenario?.type;
  let groups = catalog;
  if (scenarioType) {
    groups = catalog.filter((g) => !g.scenario || g.scenario === scenarioType);
  }
  const lanes = scenario?.lanes ?? [];
  if (lanes.length === 0) return groups;
  const laneTags = new Set<string>();
  for (const lane of lanes) {
    if ((lane.kinds ?? []).includes(kind)) {
      for (const t of lane.tags ?? []) laneTags.add(t);
    }
  }
  if (laneTags.size === 0) return [];
  return groups.filter((g) => g.tags.some((t) => laneTags.has(t)));
}

export function accessLabel(value: string, t: KnowledgeT): string {
  if (value in t.access) return t.access[value as SpaceAccessValue];
  return value;
}

export function accessHint(value: string, t: KnowledgeT): string | null {
  if (value in t.accessHint) return t.accessHint[value as SpaceAccessValue];
  return null;
}

export function ingestModeLabel(
  mode: "structured" | "unstructured",
  t: KnowledgeT,
): string {
  return mode === "structured"
    ? t.uploadModeStructured
    : t.uploadModeUnstructured;
}

export type DocumentIngestMode = "structured" | "unstructured";

export function docIngestMode(
  doc: { attrs?: Record<string, unknown> | null },
  fallback?: DocumentIngestMode | null,
): DocumentIngestMode | null {
  const raw = doc.attrs?.ingest_mode;
  if (raw === "structured" || raw === "unstructured") return raw;
  if (fallback === "structured" || fallback === "unstructured") return fallback;
  return null;
}

export function docIngestModeLabel(
  doc: { attrs?: Record<string, unknown> | null },
  t: KnowledgeT,
  fallback?: DocumentIngestMode | null,
): string | null {
  const mode = docIngestMode(doc, fallback);
  return mode ? ingestModeLabel(mode, t) : null;
}

export function roleLabel(value: string, t: KnowledgeT): string {
  if (value in t.role) return t.role[value as SpaceRoleValue];
  return value;
}

export function statusLabel(status: string, t: KnowledgeT): string {
  if (status in t.status) return t.status[status as keyof KnowledgeT["status"]];
  return status;
}

export function phaseLabel(phase: string, t: KnowledgeT): string {
  if (phase in t.phase) return t.phase[phase as keyof KnowledgeT["phase"]];
  return phase;
}

export function parseQualityLabel(
  quality: string | null | undefined,
  t: KnowledgeT,
): string | null {
  if (!quality || !(quality in t.parseQuality)) return null;
  return t.parseQuality[quality as keyof KnowledgeT["parseQuality"]];
}

export function parseQualityHint(
  quality: string | null | undefined,
  t: KnowledgeT,
): string | null {
  if (!quality || !(quality in t.parseQualityHint)) return null;
  return t.parseQualityHint[quality as keyof KnowledgeT["parseQualityHint"]];
}
