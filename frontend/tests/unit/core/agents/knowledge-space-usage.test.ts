import { describe, expect, it } from "@rstest/core";

import {
  compactAgentUsageLabel,
  formatAgentUsageLabel,
  knowledgeSpaceAgentUsageMap,
} from "@/core/agents/knowledge-space-usage";
import type { Agent } from "@/core/agents/types";

function agent(name: string, spaces: string[] | null): Agent {
  return {
    name,
    description: "",
    model: null,
    tool_groups: null,
    skills: null,
    knowledge_spaces: spaces,
  };
}

describe("knowledgeSpaceAgentUsageMap", () => {
  it("maps space ids to sorted agent names", () => {
    const map = knowledgeSpaceAgentUsageMap([
      agent("policy-reviewer-test", ["sense-ri-legal", "legal"]),
      agent("general-bot", ["sense-ri-legal"]),
      agent("no-kb", null),
    ]);
    expect(map["sense-ri-legal"]).toEqual([
      "general-bot",
      "policy-reviewer-test",
    ]);
    expect(map.legal).toEqual(["policy-reviewer-test"]);
    expect(map["no-kb"]).toBeUndefined();
  });

  it("dedupes repeated bindings", () => {
    const map = knowledgeSpaceAgentUsageMap([
      agent("a", ["space-1", " space-1 "]),
    ]);
    expect(map["space-1"]).toEqual(["a"]);
  });
});

describe("formatAgentUsageLabel", () => {
  it("joins names with comma", () => {
    expect(formatAgentUsageLabel(["b", "a"])).toBe("b, a");
  });
});

describe("compactAgentUsageLabel", () => {
  it("shows single agent as-is", () => {
    expect(compactAgentUsageLabel(["qa-helper"])).toEqual({
      text: "qa-helper",
      title: "qa-helper",
    });
  });

  it("collapses multiple agents to first plus count", () => {
    expect(compactAgentUsageLabel(["qa-helper", "recruit-helper"])).toEqual({
      text: "qa-helper +1",
      title: "qa-helper, recruit-helper",
    });
  });
});
