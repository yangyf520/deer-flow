"use client";

import { KeyIcon, SettingsIcon } from "lucide-react";
import { useMemo } from "react";

import {
  CardAction,
  ItemCard,
  itemMetaTags,
  maskMiddle,
} from "@/components/component";
import type { AgentOption, ApiKeySummary } from "@/core/api-keys";
import { useI18n } from "@/core/i18n/hooks";

const API_KEY_PREFIX = "dfk_";

function agentBindingMeta(
  agentName: string | null,
  agents: AgentOption[],
  labels: { unboundAgent: string; leadAgent: string },
): { label: string; hint?: string } {
  if (!agentName) {
    return { label: labels.unboundAgent };
  }
  if (agentName === "lead_agent") {
    return { label: labels.leadAgent, hint: agentName };
  }
  const description = agents
    .find((item) => item.name === agentName)
    ?.description?.trim();
  return {
    label: agentName,
    ...(description ? { hint: description } : {}),
  };
}

interface ApiKeyCardProps {
  apiKey: ApiKeySummary;
  agents: AgentOption[];
  onEdit?: (key: ApiKeySummary) => void;
}

export function ApiKeyCard({ apiKey, agents, onEdit }: ApiKeyCardProps) {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;

  const metaTags = useMemo(() => {
    const agentMeta = agentBindingMeta(apiKey.agent_name, agents, {
      unboundAgent: ak.unboundAgent,
      leadAgent: ak.leadAgent,
    });
    const prefixMeta = maskMiddle(apiKey.prefix, {
      leadingPrefix: API_KEY_PREFIX,
    });
    return itemMetaTags([
      {
        key: "agent",
        label: agentMeta.label,
        hint: agentMeta.hint,
      },
      {
        key: "prefix",
        label: prefixMeta,
        className: "whitespace-nowrap",
      },
    ]);
  }, [agents, ak.leadAgent, ak.unboundAgent, apiKey]);

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
