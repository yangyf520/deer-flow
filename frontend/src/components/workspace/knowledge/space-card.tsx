"use client";

import {
  BookOpenIcon,
  FileTextIcon,
  FlaskConicalIcon,
  SettingsIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useMemo } from "react";

import {
  CardAction,
  ItemCard,
  ItemCardBadge,
  itemMetaTags,
} from "@/components/component";
import { useI18n } from "@/core/i18n/hooks";
import {
  accessLabel,
  boundScenarioType,
  scenarioLabel,
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

  const metaTags = useMemo(() => {
    return itemMetaTags([
      { key: "access", label: accessLabel(space.access, kb) },
      {
        key: "scenario",
        label: bound ? scenarioLabel(bound, kb) : kb.bindScenario,
      },
    ]);
  }, [bound, kb, space.access]);

  return (
    <ItemCard
      icon={BookOpenIcon}
      iconTone="knowledge"
      title={space.id}
      description={space.description ?? space.name}
      metaTags={metaTags}
      href={href}
      badges={
        !bound ? (
          <ItemCardBadge variant="destructive">{kb.unbound}</ItemCardBadge>
        ) : undefined
      }
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
