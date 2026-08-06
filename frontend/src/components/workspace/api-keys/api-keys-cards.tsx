"use client";

import { KeyIcon, SettingsIcon } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import {
  CardAction,
  ItemCard,
  ItemRowStatusBadge,
  MetaPill,
  formatApiKeyPrefixDisplay,
} from "@/components/component";
import {
  getApiKeyMaskedDisplay,
  isApiKeyDisabled,
  type AgentOption,
  type ApiKeySummary,
} from "@/core/api-keys";
import { useI18n } from "@/core/i18n/hooks";

const API_KEY_PREFIX = "dfk_";

interface ApiKeyCardProps {
  apiKey: ApiKeySummary;
  agents: AgentOption[];
  onEdit?: (key: ApiKeySummary) => void;
}

export function ApiKeyCard({ apiKey, agents, onEdit }: ApiKeyCardProps) {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;
  const disabled = isApiKeyDisabled(apiKey);

  const metaTags = useMemo(() => {
    const agentName = apiKey.agent_name;

    let agentTag: ReactNode;
    if (!agentName) {
      agentTag = (
        <ItemRowStatusBadge key="agent" tone="warning">
          {ak.unboundAgent}
        </ItemRowStatusBadge>
      );
    } else if (agentName === "lead_agent") {
      agentTag = (
        <ItemRowStatusBadge key="agent" tone="success" title={agentName}>
          {ak.leadAgent}
        </ItemRowStatusBadge>
      );
    } else {
      const description = agents
        .find((item) => item.name === agentName)
        ?.description?.trim();
      agentTag = (
        <ItemRowStatusBadge
          key="agent"
          tone="success"
          className="w-auto max-w-[15ch] min-w-0 shrink font-mono"
          title={description ? `${agentName} — ${description}` : agentName}
        >
          <span className="block min-w-0 truncate">{agentName}</span>
        </ItemRowStatusBadge>
      );
    }

    const prefixDisplay =
      getApiKeyMaskedDisplay(apiKey.id) ??
      formatApiKeyPrefixDisplay(apiKey.prefix, {
        leadingPrefix: API_KEY_PREFIX,
      });

    return [
      <div
        key="meta"
        className="flex min-w-0 flex-nowrap items-center gap-2 overflow-hidden"
      >
        {agentTag}
        <MetaPill
          key="prefix"
          size="row"
          mono
          hint={prefixDisplay}
          className="ml-auto w-[18ch] max-w-none shrink-0 justify-center px-2"
        >
          {prefixDisplay}
        </MetaPill>
      </div>,
    ];
  }, [agents, ak.leadAgent, ak.unboundAgent, apiKey]);

  return (
    <ItemCard
      icon={KeyIcon}
      iconTone={disabled ? "disabled" : "api"}
      title={apiKey.name}
      description={apiKey.description ?? undefined}
      metaTags={metaTags}
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
