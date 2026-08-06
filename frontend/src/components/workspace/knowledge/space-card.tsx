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
import { useI18n } from "@/core/i18n/hooks";
import {
  accessHint,
  accessLabel,
  boundScenarioType,
  scenarioLabel,
  spaceCardSubtitle,
  spaceCardTitle,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

interface SpaceCardProps {
  space: Space;
  onEdit?: (space: Space) => void;
}

const actionClass =
  "min-w-0 w-full justify-center px-1 text-[11px] sm:px-1.5 sm:text-xs";

export function SpaceCard({ space, onEdit }: SpaceCardProps) {
  const { t } = useI18n();
  const kb = t.knowledge;
  const href = `/workspace/knowledge/${space.id}`;
  const bound = boundScenarioType(space);
  const isAdmin = space.my_role === "admin";
  const title = spaceCardTitle(space);
  const subtitle = spaceCardSubtitle(space, title);

  const metaTags = useMemo(() => {
    const tags: ReactNode[] = [];

    if (!bound) {
      tags.push(
        <ItemRowStatusBadge key="bind" tone="warning">
          {kb.unbound}
        </ItemRowStatusBadge>,
      );
    } else {
      tags.push(
        <ItemRowStatusBadge
          key="scenario"
          tone="success"
          className="font-mono"
          title={bound}
        >
          {scenarioLabel(bound, kb)}
        </ItemRowStatusBadge>,
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
  }, [bound, kb, space.access]);

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
