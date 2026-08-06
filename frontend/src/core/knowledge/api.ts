import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";
import { DEFAULT_LOCALE, normalizeLocale } from "../i18n";
import { getLocaleFromCookie } from "../i18n/cookies";

export const SPACE_ACCESS_VALUES = ["open", "members", "private"] as const;
export type SpaceAccessValue = (typeof SPACE_ACCESS_VALUES)[number];

export const SPACE_ROLE_VALUES = [
  "viewer",
  "editor",
  "publisher",
  "admin",
] as const;
export type SpaceRoleValue = (typeof SPACE_ROLE_VALUES)[number];

export type Space = {
  id: string;
  name: string;
  description?: string | null;
  access: string;
  owner_user_id: string;
  allowed_kinds: string[];
  /** Bound config scenarios[].type */
  scenario?: string | null;
  default_scenarios: string[];
  knowledge_version?: string;
  top_k?: number | null;
  score?: number | null;
  my_role?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export const DEFAULT_TOP_K = 8;
export const DEFAULT_SCORE = 0.35;

export function parseRetrievalPayload(topK: string, score: string) {
  const parsedTopK = Number.parseInt(topK, 10);
  const parsedScore = Number.parseFloat(score);
  return {
    top_k:
      Number.isFinite(parsedTopK) && parsedTopK >= 1 && parsedTopK <= 50
        ? parsedTopK
        : DEFAULT_TOP_K,
    score:
      Number.isFinite(parsedScore) && parsedScore >= 0 && parsedScore <= 1
        ? parsedScore
        : DEFAULT_SCORE,
  };
}

export type ScenarioPack = {
  description?: string;
  type: string;
  label?: string;
  /** Linked knowledge space id (defaults to scenario type). */
  space_id?: string;
  /** Knowledge space that owns this catalog entry. */
  host_space_id?: string;
};

export type ScenariosListResponse = {
  items: ScenarioPack[];
  total: number;
};

export type KnowledgeKind = {
  id: string;
  label?: string;
};

export type KindsListResponse = {
  items: KnowledgeKind[];
  total: number;
};

export type KnowledgeTag = {
  id: string;
  label?: string;
  scenario?: string;
};

export type KnowledgeTagGroup = {
  id: string;
  label?: string;
  tags: string[];
  scenario?: string;
};

export type KnowledgeCatalogResponse = {
  kinds: KnowledgeKind[];
  tags: KnowledgeTag[];
  tag_groups: KnowledgeTagGroup[];
  scenarios: ScenarioPack[];
};

export type ScenarioDefinitionInput = {
  code: string;
  label: string;
  description?: string;
  merge_mode?: string;
  fusion_num_queries?: number | null;
  host_space_id?: string;
};

export type SpacesListResponse = {
  items: Space[];
  total: number;
};

export type SpaceGrant = {
  id: string;
  space_id: string;
  subject_type: "user" | "dept";
  subject_id: string;
  subject_name?: string | null;
  role: SpaceRoleValue;
  granted_by?: string | null;
  created_at?: string | null;
};

export type SpaceGrantsListResponse = {
  items: SpaceGrant[];
  total: number;
};

export type KnowledgeDocument = {
  id: string;
  space_id: string;
  title: string;
  kind: string;
  status: string;
  source_filename: string;
  job_phase: string;
  progress: number;
  parse_quality?: string | null;
  parse_error?: string | null;
  error_message?: string | null;
  created_by?: string | null;
  /** Display name for uploader (email local-part); prefer over created_by UUID */
  created_by_name?: string | null;
  created_at?: string | null;
  tags?: string[];
  effective_from?: string | null;
  effective_to?: string | null;
  attrs?: Record<string, unknown>;
};

export type DocumentsListResponse = {
  items: KnowledgeDocument[];
  total: number;
  limit: number;
  offset: number;
};

export type DocumentImportResponse = {
  doc_id: string;
  status: string;
  job_phase: string;
  progress: number;
  deduped?: boolean;
  message?: string | null;
};

export type EvidenceItem = {
  id: string;
  source: string;
  kind: string;
  title: string;
  snippet: string;
  score?: number | null;
  citable_as?: string | null;
  metadata?: Record<string, unknown>;
};

export type EvidencePackResponse = {
  knowledge_version: string;
  trace_id: string;
  items: EvidenceItem[];
  answer?: string | null;
};

const base = () => `${getBackendBaseURL()}/api/v1/knowledge`;

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

export async function listScenarios(): Promise<ScenariosListResponse> {
  const res = await fetch(`${base()}/scenarios`, withLocale());
  return readJson(res, "Failed to list scenarios");
}

export async function listCatalog(): Promise<KnowledgeCatalogResponse> {
  const res = await fetch(`${base()}/catalog`, withLocale());
  return readJson(res, "Failed to load knowledge catalog");
}

export async function migrateCatalogHost(hostSpaceId: string): Promise<{
  host_space_id: string;
  updated: number;
}> {
  const res = await fetch(
    `${base()}/catalog/migrate-host`,
    withLocale({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host_space_id: hostSpaceId }),
    }),
  );
  return readJson(res, "Failed to migrate catalog host");
}

export async function upsertScenario(
  code: string,
  input: ScenarioDefinitionInput,
): Promise<ScenarioPack> {
  const res = await fetch(
    `${base()}/scenarios/${encodeURIComponent(code)}`,
    withLocale({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
  return readJson(res, "Failed to save scenario");
}

export async function deleteScenario(code: string): Promise<void> {
  const res = await fetch(`${base()}/scenarios/${encodeURIComponent(code)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    await readJson(res, "Failed to delete scenario");
  }
}

export async function listMySpaces(): Promise<SpacesListResponse> {
  const res = await fetch(`${base()}/spaces/me`);
  return readJson(res, "Failed to list spaces");
}

export async function createSpace(input: {
  name: string;
  description?: string;
  access?: string;
  id?: string;
  scenario?: string;
  allowed_kinds?: string[];
  top_k?: number;
  score?: number;
}): Promise<Space> {
  const res = await fetch(`${base()}/spaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson(res, "Failed to create space");
}

export async function updateSpace(
  spaceId: string,
  input: {
    id?: string;
    scenario?: string;
    name?: string;
    description?: string;
    access?: string;
    allowed_kinds?: string[];
    knowledge_version?: string;
    top_k?: number;
    score?: number;
  },
): Promise<Space> {
  const res = await fetch(`${base()}/spaces/${encodeURIComponent(spaceId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson(res, "Failed to update space");
}

export async function deleteSpace(spaceId: string): Promise<void> {
  const res = await fetch(`${base()}/spaces/${encodeURIComponent(spaceId)}`, {
    method: "DELETE",
  });
  if (res.status === 204 || res.ok) return;
  await readJson(res, "Failed to delete space");
}

export async function getSpace(spaceId: string): Promise<Space> {
  const res = await fetch(`${base()}/spaces/${encodeURIComponent(spaceId)}`);
  return readJson(res, "Failed to get space");
}

export async function listGrants(
  spaceId: string,
): Promise<SpaceGrantsListResponse> {
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/grants`,
  );
  return readJson(res, "Failed to list grants");
}

export async function upsertGrant(
  spaceId: string,
  input: {
    subject_type: "user" | "dept";
    subject_id: string;
    role: SpaceRoleValue;
  },
): Promise<SpaceGrant> {
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/grants`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return readJson(res, "Failed to update grant");
}

export async function deleteGrant(
  spaceId: string,
  subjectType: "user" | "dept",
  subjectId: string,
): Promise<void> {
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/grants/${encodeURIComponent(subjectType)}/${encodeURIComponent(subjectId)}`,
    { method: "DELETE" },
  );
  if (res.status === 204 || res.ok) return;
  await readJson(res, "Failed to delete grant");
}

export async function listDocuments(
  spaceId: string,
  limit = 20,
  offset = 0,
  kind?: string,
  q?: string,
): Promise<DocumentsListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (kind) params.set("kind", kind);
  if (q?.trim()) params.set("q", q.trim());
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/documents?${params.toString()}`,
  );
  return readJson(res, "Failed to list documents");
}

export async function updateDocument(
  spaceId: string,
  docId: string,
  input: {
    kind?: string;
    tags?: string[];
    effective_from?: string | null;
    effective_to?: string | null;
    title?: string;
    attrs?: Record<string, unknown>;
  },
): Promise<KnowledgeDocument> {
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/documents/${encodeURIComponent(docId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return readJson(res, "Failed to update document");
}

export async function deleteDocument(
  spaceId: string,
  docId: string,
): Promise<void> {
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/documents/${encodeURIComponent(docId)}`,
    { method: "DELETE" },
  );
  if (res.status === 204 || res.ok) return;
  await readJson(res, "Failed to delete document");
}

export async function deleteAllDocuments(spaceId: string): Promise<void> {
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/documents`,
    { method: "DELETE" },
  );
  if (res.status === 204 || res.ok) return;
  await readJson(res, "Failed to delete all documents");
}

export async function reindexDocument(
  spaceId: string,
  docId: string,
  file: File,
): Promise<DocumentImportResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/documents/${encodeURIComponent(docId)}/reindex`,
    { method: "POST", body: form },
  );
  return readJson(res, "Failed to reindex document");
}

export type DocumentChunk = {
  id: string;
  index: number;
  text: string;
  char_count: number;
  block?: string | null;
  heading_path?: string | null;
  page?: string | number | null;
  parse_quality?: string | null;
};

export type DocumentChunksResponse = {
  doc_id: string;
  title: string;
  source_filename: string;
  parse_quality?: string | null;
  parse_error?: string | null;
  items: DocumentChunk[];
  total: number;
};

export async function listDocumentChunks(
  spaceId: string,
  docId: string,
): Promise<DocumentChunksResponse> {
  const res = await fetch(
    `${base()}/spaces/${encodeURIComponent(spaceId)}/documents/${encodeURIComponent(docId)}/chunks`,
  );
  return readJson(res, "Failed to list document chunks");
}

export async function searchKnowledge(input: {
  query: string;
  spaces?: string[];
  scenario?: string;
  top_k?: number;
}): Promise<EvidencePackResponse> {
  const res = await fetch(`${base()}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson(res, "Failed to search");
}
