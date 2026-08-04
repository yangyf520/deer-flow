const STORAGE_KEY = "deerflow:knowledge:catalog-host";

export function readStoredCatalogHost(): string | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(STORAGE_KEY)?.trim();
  if (!raw) return null;
  return raw;
}

export function storeCatalogHost(spaceId: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(STORAGE_KEY, spaceId.trim());
}
