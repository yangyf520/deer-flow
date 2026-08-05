import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { DocumentImportResponse } from "./api";

export async function importDocument(
  spaceId: string,
  file: File,
  opts: {
    kind: string;
    title?: string;
    tags?: string[];
    attrs?: Record<string, unknown>;
    segments?: Array<{ text: string; metadata?: Record<string, unknown> }>;
  },
  options?: { signal?: AbortSignal },
): Promise<DocumentImportResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", opts.kind);
  if (opts.title) form.append("title", opts.title);
  for (const tag of opts.tags ?? []) {
    if (tag.trim()) form.append("tags", tag.trim());
  }
  if (opts.attrs && Object.keys(opts.attrs).length > 0) {
    form.append("attrs", JSON.stringify(opts.attrs));
  }
  if (opts.segments && opts.segments.length > 0) {
    form.append("segments", JSON.stringify(opts.segments));
  }

  const response = await fetch(
    `${getBackendBaseURL()}/api/v1/knowledge/spaces/${encodeURIComponent(spaceId)}/documents`,
    {
      method: "POST",
      body: form,
      signal: options?.signal,
    },
  );

  if (!response.ok) {
    await throwGatewayApiError(response, "Failed to import document");
  }

  return response.json() as Promise<DocumentImportResponse>;
}
