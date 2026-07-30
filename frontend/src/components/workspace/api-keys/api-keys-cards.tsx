"use client";

import { KeyIcon, SettingsIcon } from "lucide-react";
import { useMemo } from "react";

import { CardAction, ItemCard, itemMetaTags } from "@/components/component";
import type { ApiKeySummary } from "@/core/api-keys";
import { useI18n } from "@/core/i18n/hooks";

function agentBindingLabel(
  agentName: string | null,
  labels: { unboundAgent: string; leadAgent: string },
): string {
  if (!agentName) return labels.unboundAgent;
  if (agentName === "lead_agent") return labels.leadAgent;
  return agentName;
}

interface ApiKeyCardProps {
  apiKey: ApiKeySummary;
  onEdit?: (key: ApiKeySummary) => void;
}

export function ApiKeyCard({ apiKey, onEdit }: ApiKeyCardProps) {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;

  const metaTags = useMemo(() => {
    return itemMetaTags([
      {
        key: "agent",
        label: agentBindingLabel(apiKey.agent_name, {
          unboundAgent: ak.unboundAgent,
          leadAgent: ak.leadAgent,
        }),
      },
      { key: "prefix", label: apiKey.prefix },
    ]);
  }, [ak.leadAgent, ak.unboundAgent, apiKey]);

  return (
    <ItemCard
      icon={KeyIcon}
      iconTone="knowledge"
      title={apiKey.name}
      description={apiKey.description ?? undefined}
      metaTags={metaTags}
      metaTagsLayout="stacked"
      actions={
        <CardAction
          icon={SettingsIcon}
          label={ak.editButton}
          onClick={() => onEdit?.(apiKey)}
        />
      }
    />
  );
}
