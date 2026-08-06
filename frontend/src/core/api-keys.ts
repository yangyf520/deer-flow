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

export async function revokeApiKey(keyId: string): Promise<void> {
  const res = await fetch(`/api/v1/auth/api-keys/${keyId}`, {
    method: "DELETE",
    headers: getCsrfHeaders(),
  });
  if (!res.ok) {
    throw new Error("Failed to revoke API key");
  }
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
