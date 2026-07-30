import type { Translations } from "@/core/i18n/locales/types";

import type { SpaceAccessValue, SpaceRoleValue } from "./api";

type KnowledgeT = Translations["knowledge"];

export type KindCatalogEntry = { id: string };

export function kindLabel(kindId: string, t: KnowledgeT): string {
  return t.kinds[kindId] ?? kindId;
}

export function scenarioLabel(scenarioType: string, t: KnowledgeT): string {
  return t.scenarios[scenarioType] ?? scenarioType;
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

/** Kind ids configured on a scenario pack (from lanes). */
function scenarioKinds(
  scenario: { kinds?: string[] | null } | null | undefined,
): string[] {
  return (scenario?.kinds ?? []).filter(Boolean);
}

export function kindsForScenario(
  scenario: { kinds?: string[] | null } | null | undefined,
  catalog: KindCatalogEntry[] = [],
): KindCatalogEntry[] {
  const ids = scenarioKinds(scenario);
  if (ids.length === 0) return [];
  const byId = new Map(catalog.map((k) => [k.id, k]));
  return ids.map((id) => byId.get(id) ?? { id });
}

export function uploadKindsForSpace(
  space: {
    allowed_kinds?: string[] | null;
    scenario?: string | null;
    default_scenarios?: string[] | null;
  } | null,
  catalog: KindCatalogEntry[],
  scenarios?: { type: string; kinds?: string[] | null }[],
): KindCatalogEntry[] {
  const allowed = (space?.allowed_kinds ?? []).filter(Boolean);
  if (allowed.length > 0) {
    const allowSet = new Set(allowed);
    return catalog.filter((k) => allowSet.has(k.id));
  }
  const st = space?.scenario ?? space?.default_scenarios?.[0] ?? null;
  const pack =
    st && scenarios ? scenarios.find((s) => s.type === st) : undefined;
  const fromScenario = kindsForScenario(pack, catalog);
  if (fromScenario.length > 0) return fromScenario;
  return catalog;
}

export function docKindOptionsFor(
  doc: { kind: string },
  candidates: KindCatalogEntry[],
): KindCatalogEntry[] {
  if (!doc.kind || candidates.some((k) => k.id === doc.kind)) return candidates;
  return [{ id: doc.kind }, ...candidates];
}

export function defaultUploadKind(
  candidates: KindCatalogEntry[],
): string | null {
  if (candidates.length === 0) return null;
  const prefer = ["policy", "reference", "general"];
  for (const id of prefer) {
    if (candidates.some((k) => k.id === id)) return id;
  }
  return candidates[0]?.id ?? null;
}

/** Policy lane tags — align with config scenario lanes. */
export const POLICY_TAG_GROUPS = [
  { id: "national", tags: ["statute", "national-law"] as const },
  { id: "company", tags: ["company-policy"] as const },
] as const;

export type PolicyTagGroupId = (typeof POLICY_TAG_GROUPS)[number]["id"];

export function tagGroupLabel(
  groupId: PolicyTagGroupId,
  t: KnowledgeT,
): string {
  return t.tagGroups[groupId] ?? groupId;
}

export function tagsFromPolicyGroups(
  groupIds: Iterable<PolicyTagGroupId>,
): string[] {
  const want = new Set(groupIds);
  const out: string[] = [];
  for (const group of POLICY_TAG_GROUPS) {
    if (!want.has(group.id)) continue;
    out.push(...group.tags);
  }
  return [...new Set(out)];
}

export function policyGroupsFromTags(
  tags: string[] | undefined,
): PolicyTagGroupId[] {
  const have = new Set(tags ?? []);
  return POLICY_TAG_GROUPS.filter((g) => g.tags.some((t) => have.has(t))).map(
    (g) => g.id,
  );
}

export function accessLabel(value: string, t: KnowledgeT): string {
  if (value in t.access) return t.access[value as SpaceAccessValue];
  return value;
}

export function accessHint(value: string, t: KnowledgeT): string | null {
  if (value in t.accessHint) return t.accessHint[value as SpaceAccessValue];
  return null;
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
