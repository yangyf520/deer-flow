import type { Agent } from "./types";

/** Map each knowledge space id to agent names that bind it (sorted, deduped). */
export function knowledgeSpaceAgentUsageMap(
  agents: readonly Agent[],
): Record<string, string[]> {
  const map = new Map<string, Set<string>>();
  for (const agent of agents) {
    const spaces = agent.knowledge_spaces;
    if (!Array.isArray(spaces) || spaces.length === 0) continue;
    for (const spaceId of spaces) {
      const id = spaceId.trim();
      if (!id) continue;
      const bucket = map.get(id) ?? new Set<string>();
      bucket.add(agent.name);
      map.set(id, bucket);
    }
  }
  const out: Record<string, string[]> = {};
  for (const [spaceId, names] of map.entries()) {
    out[spaceId] = [...names].sort((a, b) => a.localeCompare(b));
  }
  return out;
}

/** Comma-separated label for cards; full list stays in `title`. */
export function formatAgentUsageLabel(names: readonly string[]): string {
  return names.join(", ");
}

/** Short card label: first agent + "+N" when multiple. */
export function compactAgentUsageLabel(names: readonly string[]): {
  text: string;
  title: string;
} {
  const title = formatAgentUsageLabel(names);
  if (names.length === 0) {
    return { text: "", title: "" };
  }
  if (names.length === 1) {
    return { text: names[0]!, title };
  }
  return { text: `${names[0]} +${names.length - 1}`, title };
}
