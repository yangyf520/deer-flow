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
