import { describe, expect, it } from "@rstest/core";

import {
  KNOWLEDGE_DEFAULT_TYPE_KEY,
  normalizeCodeTableFlatBundle,
} from "@/core/code-table/api";
import type { KnowledgeCodeTable } from "@/core/knowledge/api";

describe("normalizeCodeTableFlatBundle", () => {
  it("passes through flat bundles", () => {
    const flat = {
      domain: "legal",
      items: [
        {
          id: "1",
          domain: "legal",
          type_key: "industry_tag",
          code: "finance",
          label: "Finance",
          parent_code: "",
          attrs: {},
          sort_order: 0,
          enabled: true,
        },
      ],
    };
    expect(normalizeCodeTableFlatBundle("legal", flat)).toBe(flat);
  });

  it("maps knowledge catalog industry tags to flat entries", () => {
    const catalog: KnowledgeCodeTable = {
      kinds: [],
      tags: [],
      tag_groups: [],
      scenarios: [],
      industry_tags: [
        {
          id: "legal",
          label: "Legal",
          keywords: ["law"],
          department: ["compliance"],
          aliases: ["法务"],
        },
      ],
    };
    const flat = normalizeCodeTableFlatBundle(
      "knowledge",
      catalog,
      KNOWLEDGE_DEFAULT_TYPE_KEY,
    );
    expect(flat.items).toHaveLength(1);
    expect(flat.items[0]).toMatchObject({
      domain: "knowledge",
      type_key: KNOWLEDGE_DEFAULT_TYPE_KEY,
      code: "legal",
      label: "Legal",
      attrs: {
        keywords: ["law"],
        department: ["compliance"],
        aliases: ["法务"],
      },
    });
  });
});
