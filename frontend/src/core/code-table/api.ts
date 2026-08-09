import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { DEFAULT_LOCALE, normalizeLocale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";
import type {
  KnowledgeCodeTable,
  KnowledgeIndustryTag,
  KnowledgeKind,
  KnowledgeTag,
  KnowledgeTagGroup,
  ScenarioPack,
} from "@/core/knowledge/api";

export const KNOWLEDGE_CODE_TABLE_DOMAIN = "knowledge";
export const KNOWLEDGE_DEFAULT_TYPE_KEY = "industry_tag";

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
  type_key: string;
  label?: string;
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
): Promise<void> {
  const params = new URLSearchParams({ type_key: typeKey });
  const res = await fetch(
    `${base()}/domains/${encodeURIComponent(domain)}/entries/${encodeURIComponent(code)}?${params.toString()}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    await readJson(res, "Failed to delete code-table entry");
  }
}

export type {
  KnowledgeCodeTable,
  KnowledgeIndustryTag,
  KnowledgeKind,
  KnowledgeTag,
  KnowledgeTagGroup,
  ScenarioPack,
};
