"use client";

import {
  BookOpenIcon,
  FileTextIcon,
  FlaskConicalIcon,
  SettingsIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useMemo, type ReactNode } from "react";

import { CardAction, ItemCard, MetaPill } from "@/components/component";
import { formatAgentUsageLabel } from "@/core/agents/knowledge-space-usage";
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
}

const actionClass =
  "min-w-0 w-full justify-center px-1 text-[11px] sm:px-1.5 sm:text-xs";

export function SpaceCard({
  space,
  onEdit,
  usingAgentNames = null,
}: SpaceCardProps) {
  const { t } = useI18n();
  const kb = t.knowledge;
  const href = `/workspace/knowledge/${space.id}`;
  const isAdmin = space.my_role === "admin";
  const title = spaceCardTitle(space);
  const subtitle = spaceCardSubtitle(space, title);

  const metaTags = useMemo(() => {
    const tags: ReactNode[] = [];

    if (usingAgentNames && usingAgentNames.length > 0) {
      const label = formatAgentUsageLabel(usingAgentNames);
      tags.push(
        <MetaPill
          key="agents"
          mono
          size="row"
          hint={label}
          className="max-w-full min-w-0 shrink truncate"
        >
          {label}
        </MetaPill>,
      );
    }

    const access = accessLabel(space.access, kb);
    const accessDetail = accessHint(space.access, kb);
    tags.push(
      <MetaPill key="access" size="row" hint={accessDetail ?? undefined}>
        {access}
      </MetaPill>,
    );

    return tags;
  }, [kb, space.access, usingAgentNames]);

  return (
    <ItemCard
      icon={BookOpenIcon}
      iconTone="knowledge"
      title={title}
      description={subtitle}
      metaTags={metaTags}
      metaTagsLayout="inline-grow-leading"
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
