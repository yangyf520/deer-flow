import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ParsedDetail = {
  segment_label?: string;
  chapter_path?: string;
  body?: string;
  ref_labels?: string[];
  /** Base64-encoded 1-based source line number (matches knowledge embed `row_no`). */
  row_no_b64?: string;
};

export type ParsedDocumentData = {
  title?: string;
  details?: ParsedDetail[];
};

export type DocParseMeta = {
  source_filename: string;
  segment_prompt_hash: string;
  block_count: number;
  batch_count: number;
  parse_quality?: string | null;
  parse_backend?: string | null;
  warnings?: string[];
};

export type DocParseResponse = {
  data: ParsedDocumentData;
  meta: DocParseMeta;
};

export function defaultStructuredSegmentPrompt(locale: string): string {
  return defaultLegalSegmentPrompt(locale);
}

export function resolveSegmentPrompt(
  segmentPrompt: string | undefined,
  locale: string,
): string {
  const trimmed = segmentPrompt?.trim();
  if (!trimmed) return defaultStructuredSegmentPrompt(locale);
  return trimmed;
}

export function defaultLegalSegmentPrompt(locale: string): string {
  if (locale.startsWith("zh")) {
    return [
      "你是法规文档切条助手。根据下文「文档块」切分为条款 JSON。",
      "要求：只输出一个 JSON 对象，不要 markdown 围栏；保留条号 segment_label、章节 chapter_path、正文 body；引用写 ref_labels。",
      '输出格式示例：{"title":"…","details":[{"segment_label":"第1条","chapter_path":"…","body":"…","ref_labels":[]}]}',
    ].join("\n");
  }
  return [
    "You are a legal document segmentation assistant. Split the document block below into clause JSON.",
    "Return one JSON object only, with no markdown fences. Include segment_label, chapter_path, body, and ref_labels.",
    'Example: {"title":"…","details":[{"segment_label":"Section 1","chapter_path":"…","body":"…","ref_labels":[]}]}',
  ].join("\n");
}

export function parsedDocumentToMarkdown(data: ParsedDocumentData): string {
  const lines: string[] = [];
  const title = data.title?.trim();
  if (title) {
    lines.push(`# ${title}`, "");
  }

  for (const detail of data.details ?? []) {
    const heading = [detail.chapter_path, detail.segment_label]
      .map((part) => part?.trim())
      .filter(Boolean)
      .join(" / ");
    if (heading) {
      lines.push(`## ${heading}`, "");
    }
    const body = detail.body?.trim();
    if (body) {
      lines.push(body, "");
    }
  }

  if (lines.length > 0) {
    return `${lines.join("\n").trim()}\n`;
  }

  return `${JSON.stringify(data, null, 2)}\n`;
}

export function parsedDocumentTitle(
  data: ParsedDocumentData,
  fallbackFilename: string,
): string {
  const title = data.title?.trim();
  if (title) return title;
  const stem = fallbackFilename.replace(/\.[^.]+$/, "").trim();
  return stem || fallbackFilename;
}

export function structuredMarkdownFile(
  data: ParsedDocumentData,
  fallbackFilename: string,
): { file: File; title: string } {
  const title = parsedDocumentTitle(data, fallbackFilename);
  const markdown = parsedDocumentToMarkdown(data);
  const safeStem = title.replace(/[^\w.\u4e00-\u9fff-]+/g, "_") || "document";
  return {
    title,
    file: new File([markdown], `${safeStem}.md`, { type: "text/markdown" }),
  };
}

export async function parseDocument(
  file: File,
  segmentPrompt: string,
  options?: { signal?: AbortSignal },
): Promise<DocParseResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("segment_prompt", segmentPrompt);

  const response = await fetch(`${getBackendBaseURL()}/api/v1/document/parse`, {
    method: "POST",
    body: form,
    signal: options?.signal,
  });

  if (!response.ok) {
    await throwGatewayApiError(response, "Failed to parse document");
  }

  return response.json() as Promise<DocParseResponse>;
}
