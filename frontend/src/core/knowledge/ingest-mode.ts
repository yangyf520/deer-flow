import type { UploadMode } from "@/app/workspace/knowledge/ui";

const storageKey = (spaceId: string) =>
  `deerflow:knowledge:ingest-mode:${spaceId}`;

export function readStoredIngestMode(spaceId: string): UploadMode {
  if (typeof window === "undefined") return "unstructured";
  return sessionStorage.getItem(storageKey(spaceId)) === "structured"
    ? "structured"
    : "unstructured";
}

export function storeIngestMode(spaceId: string, mode: UploadMode): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(storageKey(spaceId), mode);
}

const docStorageKey = (docId: string) =>
  `deerflow:knowledge:doc-ingest-mode:${docId}`;

export function readDocIngestMode(docId: string): UploadMode | null {
  if (typeof window === "undefined") return null;
  const stored = sessionStorage.getItem(docStorageKey(docId));
  return stored === "structured" || stored === "unstructured" ? stored : null;
}

export function storeDocIngestMode(docId: string, mode: UploadMode): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(docStorageKey(docId), mode);
}
