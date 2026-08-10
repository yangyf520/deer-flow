import { describe, expect, it } from "@rstest/core";

import {
  CODE_TABLE_RESERVED_TYPE_KEY,
  codeTableDomainDisplayName,
  groupCodeTableDomainSummaries,
  isCodeTableRootDomainSummary,
  primaryCodeTableDomainCategory,
  type CodeTableDomainSummary,
} from "@/core/code-table/api";

describe("groupCodeTableDomainSummaries", () => {
  it("merges categories under one domain row", () => {
    const items: CodeTableDomainSummary[] = [
      { domain: "legal", type_key: "industry_tag", entry_count: 2 },
      { domain: "legal", type_key: "status", entry_count: 3, label: "Legal" },
    ];
    expect(groupCodeTableDomainSummaries(items)).toEqual([
      {
        domain: "legal",
        type_key: "industry_tag",
        entry_count: 5,
        label: "Legal",
      },
    ]);
  });

  it("drops reserved type_key rows from the root list", () => {
    const items: CodeTableDomainSummary[] = [
      {
        domain: "知识库场景码表",
        type_key: CODE_TABLE_RESERVED_TYPE_KEY,
        entry_count: 1,
        label: "知识库场景码表",
      },
      { domain: "legal", type_key: "industry_tag", entry_count: 1 },
    ];
    expect(groupCodeTableDomainSummaries(items)).toEqual([
      { domain: "legal", type_key: "industry_tag", entry_count: 1 },
    ]);
  });
});

describe("codeTableDomainDisplayName", () => {
  it("prefers label and knowledge fallback", () => {
    expect(
      codeTableDomainDisplayName(
        { domain: "legal", type_key: "entry", entry_count: 0, label: "法务" },
        "Knowledge tags",
      ),
    ).toBe("法务");
    expect(
      codeTableDomainDisplayName(
        { domain: "knowledge", type_key: "industry_tag", entry_count: 0 },
        "Knowledge tags",
      ),
    ).toBe("Knowledge tags");
  });
});

describe("primaryCodeTableDomainCategory", () => {
  it("prefers labeled category for edit/create defaults", () => {
    const items: CodeTableDomainSummary[] = [
      { domain: "legal", type_key: "industry_tag", entry_count: 0 },
      { domain: "legal", type_key: "status", entry_count: 2, label: "Legal" },
    ];
    expect(primaryCodeTableDomainCategory(items, "legal")).toMatchObject({
      type_key: "status",
      label: "Legal",
    });
  });

  it("ignores reserved type_key categories", () => {
    expect(
      isCodeTableRootDomainSummary({
        domain: "x",
        type_key: CODE_TABLE_RESERVED_TYPE_KEY,
        entry_count: 0,
      }),
    ).toBe(false);
    expect(
      primaryCodeTableDomainCategory(
        [
          {
            domain: "x",
            type_key: CODE_TABLE_RESERVED_TYPE_KEY,
            entry_count: 1,
          },
        ],
        "x",
      ),
    ).toBeUndefined();
  });
});
