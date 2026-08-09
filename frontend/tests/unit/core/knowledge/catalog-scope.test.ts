import { describe, expect, it } from "@rstest/core";

import type { KnowledgeCodeTable } from "@/core/knowledge/api";
import {
  catalogHasContent,
  catalogScopeForHost,
  scenarioCodesForHost,
} from "@/core/knowledge/catalog-scope";

const table: KnowledgeCodeTable = {
  scenarios: [
    { type: "general-qa", host_space_id: "license" },
    { type: "policy-review", host_space_id: "other" },
    { type: "draft", host_space_id: "" },
  ],
  tags: [
    { id: "general", scenario: "general-qa" },
    { id: "statute", scenario: "policy-review" },
    { id: "company-policy", scenario: "draft" },
  ],
  kinds: [{ id: "policy" }],
  tag_groups: [
    { id: "national", tags: ["statute"], scenario: "policy-review" },
  ],
  industry_tags: [],
};

describe("scenarioCodesForHost", () => {
  it("returns assigned scenario codes for the host", () => {
    expect(scenarioCodesForHost(table.scenarios, "license")).toEqual([
      "general-qa",
    ]);
  });

  it("falls back to unassigned scenarios when host has none assigned", () => {
    expect(scenarioCodesForHost(table.scenarios, "new-space")).toEqual([
      "draft",
    ]);
  });
});

describe("catalogScopeForHost", () => {
  it("filters tags and tag groups by host scenario scope", () => {
    const scope = catalogScopeForHost(table, "license");
    expect(scope.tags.map((t) => t.id)).toEqual(["general"]);
    expect(scope.scenarios.map((s) => s.type)).toEqual(["general-qa"]);
    expect(scope.kinds).toHaveLength(1);
    expect(scope.tag_groups).toHaveLength(0);
  });

  it("includes unassigned catalog entries while host has no assigned scenarios", () => {
    const scope = catalogScopeForHost(table, "new-space");
    expect(scope.tags.map((t) => t.id)).toEqual(["company-policy"]);
    expect(scope.scenarios).toHaveLength(0);
  });

  it("falls back to all industry tags when host does not match space_id", () => {
    const tableWithIndustry: KnowledgeCodeTable = {
      ...table,
      industry_tags: [
        {
          id: "文娱",
          label: "文娱",
          space_id: "license",
          keywords: ["影视"],
        },
      ],
    };
    const scope = catalogScopeForHost(tableWithIndustry, "other-space");
    expect(scope.industry_tags.map((t) => t.id)).toEqual(["文娱"]);
  });
});

describe("catalogHasContent", () => {
  it("is true when any catalog slice has rows", () => {
    expect(
      catalogHasContent({
        scenarioCodes: ["general-qa"],
        scenarios: [],
        industry_tags: [],
        tags: [{ id: "general", scenario: "general-qa" }],
        kinds: [],
        tag_groups: [],
      }),
    ).toBe(true);
  });

  it("is false for an empty scope", () => {
    expect(
      catalogHasContent({
        scenarioCodes: [],
        scenarios: [],
        industry_tags: [],
        tags: [],
        kinds: [],
        tag_groups: [],
      }),
    ).toBe(false);
  });
});
