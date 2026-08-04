import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type DocumentEmbedResponse = {
  doc_id: string;
  status: string;
  job_phase: string;
  progress: number;
  deduped?: boolean;
  message?: string | null;
};

export async function embedDocument(
  spaceId: string,
  file: File,
  opts: { kind: string; title?: string; tags?: string[] },
  options?: { signal?: AbortSignal },
): Promise<DocumentEmbedResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", opts.kind);
  if (opts.title) form.append("title", opts.title);
  for (const tag of opts.tags ?? []) {
    if (tag.trim()) form.append("tags", tag.trim());
  }

  const response = await fetch(
    `${getBackendBaseURL()}/api/doc/embed/${encodeURIComponent(spaceId)}`,
    {
      method: "POST",
      body: form,
      signal: options?.signal,
    },
  );

  if (!response.ok) {
    await throwGatewayApiError(response, "Failed to embed document");
  }

  return response.json() as Promise<DocumentEmbedResponse>;
}
