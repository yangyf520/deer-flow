import type {
  KnowledgeCodeTable,
  KnowledgeIndustryTag,
  KnowledgeKind,
  KnowledgeTag,
  KnowledgeTagGroup,
  ScenarioPack,
} from "./api";
import { scenarioInHostSpace, scenarioUnassigned } from "./labels";

export type CatalogScope = {
  scenarioCodes: string[];
  scenarios: ScenarioPack[];
  industry_tags: KnowledgeIndustryTag[];
  tags: KnowledgeTag[];
  kinds: KnowledgeKind[];
  tag_groups: KnowledgeTagGroup[];
};

export const emptyCatalogScope = (): CatalogScope => ({
  scenarioCodes: [],
  scenarios: [],
  industry_tags: [],
  tags: [],
  kinds: [],
  tag_groups: [],
});

function industryTagsForHost(
  items: KnowledgeIndustryTag[],
  hostSpaceId: string | null,
): KnowledgeIndustryTag[] {
  if (items.length === 0) return [];
  if (!hostSpaceId) return items;
  const scoped = items.filter((item) => {
    const spaceId = item.space_id?.trim();
    return !spaceId || spaceId === hostSpaceId;
  });
  return scoped.length > 0 ? scoped : items;
}

export function scenarioCodesForHost(
  scenarios: ScenarioPack[],
  hostSpaceId: string | null,
): string[] {
  if (!hostSpaceId) return [];
  const assigned = scenarios.filter((s) => scenarioInHostSpace(s, hostSpaceId));
  if (assigned.length > 0) {
    return assigned.map((s) => s.type);
  }
  return scenarios.filter(scenarioUnassigned).map((s) => s.type);
}

export function catalogScopeForHost(
  codeTable: KnowledgeCodeTable,
  hostSpaceId: string | null,
): CatalogScope {
  const scenarios = codeTable.scenarios;
  const scenarioCodes = scenarioCodesForHost(scenarios, hostSpaceId);
  const codeSet = new Set(scenarioCodes);

  const scopedScenarios =
    hostSpaceId != null
      ? scenarios.filter((s) => scenarioInHostSpace(s, hostSpaceId))
      : [];

  const inScope = (scenario?: string) => {
    if (!hostSpaceId || !scenario) return false;
    return codeSet.has(scenario);
  };

  const hasScopedCatalog = scenarioCodes.length > 0;

  return {
    scenarioCodes,
    scenarios: scopedScenarios,
    industry_tags: industryTagsForHost(
      codeTable.industry_tags ?? [],
      hostSpaceId,
    ),
    tags: codeTable.tags.filter((t) => inScope(t.scenario)),
    kinds: hasScopedCatalog ? codeTable.kinds : [],
    tag_groups: codeTable.tag_groups.filter((g) => inScope(g.scenario)),
  };
}

export function catalogHasContent(scope: CatalogScope): boolean {
  return (
    (scope.industry_tags?.length ?? 0) > 0 ||
    (scope.tags?.length ?? 0) > 0 ||
    (scope.kinds?.length ?? 0) > 0 ||
    (scope.tag_groups?.length ?? 0) > 0 ||
    (scope.scenarios?.length ?? 0) > 0
  );
}
