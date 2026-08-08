"use client";

import {
  BookOpenIcon,
  FileTextIcon,
  FlaskConicalIcon,
  SettingsIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useMemo, type ReactNode } from "react";

import {
  CardAction,
  ItemCard,
  ItemRowStatusBadge,
  MetaPill,
} from "@/components/component";
import type { Agent } from "@/core/agents";
import {
  agentUsageBadgeTitle,
  compactAgentUsageLabel,
} from "@/core/agents/knowledge-space-usage";
import { useI18n } from "@/core/i18n/hooks";
import {
  accessHint,
  accessLabel,
  spaceCardSubtitle,
  spaceCardTitle,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

interface SpaceCardProps {
  space: Space;
  onEdit?: (space: Space) => void;
  /** Agent names bound to this space; `null` when agents API is off or still loading. */
  usingAgentNames?: string[] | null;
  agents?: readonly Agent[];
}

const actionClass =
  "min-w-0 w-full justify-center px-1 text-[11px] sm:px-1.5 sm:text-xs";

export function SpaceCard({
  space,
  onEdit,
  usingAgentNames = null,
  agents = [],
}: SpaceCardProps) {
  const { t } = useI18n();
  const kb = t.knowledge;
  const href = `/workspace/knowledge/${space.id}`;
  const isAdmin = space.my_role === "admin";
  const title = spaceCardTitle(space);
  const subtitle = spaceCardSubtitle(space, title);

  const metaTags = useMemo(() => {
    const access = accessLabel(space.access, kb);
    const accessDetail = accessHint(space.access, kb);
    const accessTag = (
      <MetaPill key="access" size="row" hint={accessDetail ?? undefined}>
        {access}
      </MetaPill>
    );

    if (usingAgentNames === null) {
      return [accessTag];
    }

    let agentTag: ReactNode;
    if (usingAgentNames.length === 0) {
      agentTag = (
        <ItemRowStatusBadge key="agents" tone="warning">
          {kb.noAgentsUsing}
        </ItemRowStatusBadge>
      );
    } else {
      const { text } = compactAgentUsageLabel(usingAgentNames);
      agentTag = (
        <ItemRowStatusBadge
          key="agents"
          tone="success"
          className="w-auto max-w-[15ch] min-w-0 shrink font-mono"
          title={agentUsageBadgeTitle(usingAgentNames, agents)}
        >
          <span className="block min-w-0 truncate">{text}</span>
        </ItemRowStatusBadge>
      );
    }

    return [
      <div
        key="meta"
        className="flex min-w-0 flex-nowrap items-center gap-2 overflow-hidden"
      >
        {agentTag}
        {accessTag}
      </div>,
    ];
  }, [agents, kb, space.access, usingAgentNames]);

  return (
    <ItemCard
      icon={BookOpenIcon}
      iconTone="knowledge"
      title={title}
      description={subtitle}
      metaTags={metaTags}
      href={href}
      actions={
        <div
          className={cn(
            "grid w-full min-w-0 gap-1",
            isAdmin ? "grid-cols-4" : "grid-cols-2",
          )}
        >
          <CardAction
            href={href}
            icon={FileTextIcon}
            label={kb.documents}
            className={actionClass}
          />
          <CardAction
            href={`${href}/eval`}
            icon={FlaskConicalIcon}
            label={kb.eval}
            className={actionClass}
          />
          {isAdmin ? (
            <>
              <CardAction
                href={`${href}/grants`}
                icon={ShieldCheckIcon}
                label={kb.grants}
                className={actionClass}
              />
              <CardAction
                icon={SettingsIcon}
                label={t.common.edit}
                className={actionClass}
                onClick={() => onEdit?.(space)}
              />
            </>
          ) : null}
        </div>
      }
    />
  );
}
