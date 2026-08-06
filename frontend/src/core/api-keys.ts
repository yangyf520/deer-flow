import { useQuery } from "@tanstack/react-query";

import { fetch, getCsrfHeaders } from "@/core/api/fetcher";

export type ApiKeySummary = {
  id: string;
  name: string;
  description: string | null;
  prefix: string;
  agent_name: string | null;
  created_by_name: string | null;
  created_at: string;
  revoked_at: string | null;
};

export type ApiKeyCreateResponse = ApiKeySummary & {
  key: string;
};

export type AgentOption = {
  name: string;
  description?: string;
};

export async function listApiKeys(): Promise<ApiKeySummary[]> {
  const res = await fetch("/api/v1/auth/api-keys");
  if (!res.ok) {
    throw new Error("Failed to load API keys");
  }
  const data = (await res.json()) as { keys: ApiKeySummary[] };
  return data.keys;
}

export async function listAgentOptions(): Promise<AgentOption[]> {
  const res = await fetch("/api/agents");
  if (!res.ok) {
    return [];
  }
  const data = (await res.json()) as { agents: AgentOption[] };
  return data.agents;
}

export async function createApiKey(input: {
  name: string;
  description?: string | null;
  agent_name: string | null;
}): Promise<ApiKeyCreateResponse> {
  const res = await fetch("/api/v1/auth/api-keys", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getCsrfHeaders(),
    },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const data = (await res.json()) as { detail?: string };
    throw new Error(data.detail ?? "Failed to create API key");
  }
  return (await res.json()) as ApiKeyCreateResponse;
}

export async function updateApiKey(
  keyId: string,
  input: {
    name?: string;
    description?: string | null;
    agent_name?: string | null;
  },
): Promise<ApiKeySummary> {
  const res = await fetch(`/api/v1/auth/api-keys/${keyId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...getCsrfHeaders(),
    },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const data = (await res.json()) as { detail?: string };
    throw new Error(data.detail ?? "Failed to update API key");
  }
  return (await res.json()) as ApiKeySummary;
}

export function isApiKeyDisabled(key: ApiKeySummary): boolean {
  return key.revoked_at != null;
}

export async function disableApiKey(keyId: string): Promise<void> {
  const res = await fetch(`/api/v1/auth/api-keys/${keyId}/disable`, {
    method: "POST",
    headers: getCsrfHeaders(),
  });
  if (!res.ok) {
    throw new Error("Failed to disable API key");
  }
}

export async function enableApiKey(keyId: string): Promise<void> {
  const res = await fetch(`/api/v1/auth/api-keys/${keyId}/enable`, {
    method: "POST",
    headers: getCsrfHeaders(),
  });
  if (!res.ok) {
    throw new Error("Failed to enable API key");
  }
}

export async function deleteApiKey(keyId: string): Promise<void> {
  const res = await fetch(`/api/v1/auth/api-keys/${keyId}`, {
    method: "DELETE",
    headers: getCsrfHeaders(),
  });
  if (!res.ok) {
    throw new Error("Failed to delete API key");
  }
  forgetApiKeyMaskedDisplay(keyId);
}

const API_KEY_MASKED_DISPLAY_KEY = "deerflow:api-key-masked-display";

function readMaskedDisplayStore(): Record<string, string> {
  if (typeof window === "undefined") {
    return {};
  }
  try {
    const raw = window.localStorage.getItem(API_KEY_MASKED_DISPLAY_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
  } catch {
    return {};
  }
}

function writeMaskedDisplayStore(store: Record<string, string>) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(
      API_KEY_MASKED_DISPLAY_KEY,
      JSON.stringify(store),
    );
  } catch {
    // Best-effort only — list cards fall back to prefix masking.
  }
}

/** Persist masked label from the one-time full key shown at creation. */
export function rememberApiKeyMaskedDisplay(keyId: string, masked: string) {
  const trimmed = masked.trim();
  if (!keyId || !trimmed) {
    return;
  }
  const store = readMaskedDisplayStore();
  store[keyId] = trimmed;
  writeMaskedDisplayStore(store);
}

export function getApiKeyMaskedDisplay(keyId: string): string | null {
  return readMaskedDisplayStore()[keyId] ?? null;
}

export function forgetApiKeyMaskedDisplay(keyId: string) {
  const store = readMaskedDisplayStore();
  if (!(keyId in store)) {
    return;
  }
  delete store[keyId];
  writeMaskedDisplayStore(store);
}

export function useApiKeys() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["api-keys"],
    queryFn: listApiKeys,
  });
  return {
    keys: data ?? [],
    isLoading,
    error,
    refetch,
  };
}
