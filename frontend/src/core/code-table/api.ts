import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { DEFAULT_LOCALE, normalizeLocale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";
import type { KnowledgeCodeTable } from "@/core/knowledge/api";

export const KNOWLEDGE_CODE_TABLE_DOMAIN = "knowledge";
export const KNOWLEDGE_DEFAULT_TYPE_KEY = "industry_tag";
export const DEFAULT_CODE_TABLE_TYPE_KEY = "entry";

export type CodeTableFlatEntry = {
  id: string;
  domain: string;
  type_key: string;
  code: string;
  label: string;
  parent_code: string;
  attrs: Record<string, unknown>;
  sort_order: number;
  enabled: boolean;
};

export type CodeTableDomainSummary = {
  domain: string;
  type_key: string;
  label?: string;
  parent_code?: string;
  entry_count: number;
};

export type CodeTableDomainsResponse = {
  items: CodeTableDomainSummary[];
  domains: string[];
};

export type CodeTableFlatBundle = {
  domain: string;
  items: CodeTableFlatEntry[];
};

export function isCodeTableFlatBundle(
  bundle: KnowledgeCodeTable | CodeTableFlatBundle,
): bundle is CodeTableFlatBundle {
  return Array.isArray((bundle as CodeTableFlatBundle).items);
}

/** Knowledge domain returns a structured catalog; entry panels need flat rows. */
export function normalizeCodeTableFlatBundle(
  domain: string,
  bundle: KnowledgeCodeTable | CodeTableFlatBundle,
  typeKey: string = KNOWLEDGE_DEFAULT_TYPE_KEY,
): CodeTableFlatBundle {
  if (isCodeTableFlatBundle(bundle)) {
    return bundle;
  }
  const items: CodeTableFlatEntry[] = (bundle.industry_tags ?? []).map(
    (tag) => ({
      id: tag.id,
      domain,
      type_key: typeKey,
      code: tag.id,
      label: tag.label?.trim() ?? tag.id,
      parent_code: "",
      attrs: {
        keywords: tag.keywords ?? [],
        department: tag.department ?? [],
        aliases: tag.aliases ?? [],
        ...(tag.space_id ? { space_id: tag.space_id } : {}),
      },
      sort_order: 0,
      enabled: true,
    }),
  );
  return { domain, items };
}

/** Internal pub_codes marker — not a user-facing type key. */
export const CODE_TABLE_RESERVED_TYPE_KEY = "_category";
/** Internal pub_codes marker row code — never show in UI lists. */
export const CODE_TABLE_RESERVED_ENTRY_CODE = "_category";

export function isCodeTableUserEntry(entry: { code: string }): boolean {
  return entry.code !== CODE_TABLE_RESERVED_ENTRY_CODE;
}

export function isCodeTableRootDomainSummary(
  item: CodeTableDomainSummary,
): boolean {
  return item.type_key !== CODE_TABLE_RESERVED_TYPE_KEY;
}

/** Root list shows one row per business domain; type_key is in-domain detail. */
export function groupCodeTableDomainSummaries(
  items: readonly CodeTableDomainSummary[],
): CodeTableDomainSummary[] {
  const byDomain = new Map<string, CodeTableDomainSummary>();
  for (const item of items) {
    if (!isCodeTableRootDomainSummary(item)) continue;
    const existing = byDomain.get(item.domain);
    if (!existing) {
      byDomain.set(item.domain, { ...item });
      continue;
    }
    existing.entry_count += item.entry_count;
    if (!existing.label?.trim() && item.label?.trim()) {
      existing.label = item.label;
    }
    if (!existing.parent_code?.trim() && item.parent_code?.trim()) {
      existing.parent_code = item.parent_code;
    }
  }
  return [...byDomain.values()].sort((a, b) =>
    a.domain.localeCompare(b.domain),
  );
}

export function codeTableDomainDisplayName(
  item: CodeTableDomainSummary,
  knowledgeLabel: string,
): string {
  const label = item.label?.trim();
  if (label) return label;
  if (item.domain === KNOWLEDGE_CODE_TABLE_DOMAIN) return knowledgeLabel;
  return item.domain;
}

export function primaryCodeTableDomainCategory(
  items: readonly CodeTableDomainSummary[],
  domain: string,
): CodeTableDomainSummary | undefined {
  const matches = items.filter(
    (item) => item.domain === domain && isCodeTableRootDomainSummary(item),
  );
  if (matches.length === 0) return undefined;
  return (
    matches.find((item) => item.label?.trim()) ??
    matches.find((item) => item.entry_count > 0) ??
    matches[0]
  );
}

const base = () => `${getBackendBaseURL()}/api/v1/code-table`;

function withLocale(init?: RequestInit): RequestInit {
  const locale = normalizeLocale(getLocaleFromCookie() ?? DEFAULT_LOCALE);
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept-Language")) {
    headers.set("Accept-Language", locale);
  }
  return { ...init, headers };
}

async function readJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    let detail = fallback;
    try {
      const body = await res.json();
      const d = body.detail ?? body;
      if (typeof d === "string") {
        detail = d;
      } else if (d && typeof d === "object" && "message" in d) {
        detail = String((d as { message: unknown }).message);
      } else {
        detail = JSON.stringify(d);
      }
    } catch {
      /* ignore */
    }
    throw new Error(`${fallback}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function loadCodeTableBundle(
  domain: string,
): Promise<KnowledgeCodeTable | CodeTableFlatBundle> {
  const params = new URLSearchParams({ domain });
  const res = await fetch(
    `${base()}/bundle?${params.toString()}`,
    withLocale(),
  );
  return readJson(res, "Failed to load code table");
}

export async function loadKnowledgeCodeTable(): Promise<KnowledgeCodeTable> {
  return loadCodeTableBundle(
    KNOWLEDGE_CODE_TABLE_DOMAIN,
  ) as Promise<KnowledgeCodeTable>;
}

export async function listCodeTableDomains(): Promise<CodeTableDomainsResponse> {
  const res = await fetch(`${base()}/domains`, withLocale());
  return readJson(res, "Failed to list code-table domains");
}

export async function createCodeTableDomain(input: {
  domain: string;
  code: string;
  label?: string;
  type_key?: string;
  attrs?: Record<string, unknown>;
}): Promise<CodeTableDomainSummary> {
  const res = await fetch(
    `${base()}/domains`,
    withLocale({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
  return readJson(res, "Failed to create code-table domain");
}

export async function updateCodeTableDomain(
  domain: string,
  input: { type_key: string; new_type_key?: string; label: string },
): Promise<CodeTableDomainSummary> {
  const res = await fetch(
    `${base()}/domains/${encodeURIComponent(domain)}`,
    withLocale({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type_key: input.type_key,
        new_type_key: input.new_type_key ?? "",
        label: input.label,
      }),
    }),
  );
  return readJson(res, "Failed to update code-table domain");
}

export async function deleteCodeTableDomain(
  domain: string,
): Promise<{ domain: string; deleted: number }> {
  const res = await fetch(`${base()}/domains/${encodeURIComponent(domain)}`, {
    method: "DELETE",
  });
  return readJson(res, "Failed to delete code-table domain");
}

export async function createCodeTableEntry(
  domain: string,
  input: {
    type_key: string;
    code: string;
    label: string;
    parent_code?: string;
    attrs?: Record<string, unknown>;
  },
): Promise<CodeTableFlatEntry> {
  const res = await fetch(
    `${base()}/domains/${encodeURIComponent(domain)}/entries`,
    withLocale({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
  return readJson(res, "Failed to create code-table entry");
}

export async function updateCodeTableEntry(
  domain: string,
  code: string,
  input: {
    type_key: string;
    label: string;
    parent_code?: string;
    attrs?: Record<string, unknown>;
  },
): Promise<CodeTableFlatEntry> {
  const res = await fetch(
    `${base()}/domains/${encodeURIComponent(domain)}/entries/${encodeURIComponent(code)}`,
    withLocale({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
  return readJson(res, "Failed to update code-table entry");
}

export async function deleteCodeTableEntry(
  domain: string,
  code: string,
  typeKey: string,
  parentCode = "",
): Promise<void> {
  const params = new URLSearchParams({ type_key: typeKey });
  if (parentCode.trim()) {
    params.set("parent_code", parentCode.trim());
  }
  const res = await fetch(
    `${base()}/domains/${encodeURIComponent(domain)}/entries/${encodeURIComponent(code)}?${params.toString()}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    await readJson(res, "Failed to delete code-table entry");
  }
}
