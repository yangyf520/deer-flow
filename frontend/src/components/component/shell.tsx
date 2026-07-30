"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import {
  workspaceGlassHeaderClass,
  workspaceHeaderAccentClass,
  workspacePageBodyGapClass,
  workspacePageBodyPaddingClass,
  workspacePageHeaderStripClass,
  workspacePageInsetXClass,
  workspacePageScrollBodyClass,
} from "./styles";

export function Shell({
  header,
  children,
  className,
  bodyClassName,
  density = "compact",
  fillBody = false,
  contentClassName,
  contentGapClassName,
}: {
  header: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  density?: "compact" | "comfortable";
  fillBody?: boolean;
  contentClassName?: string;
  contentGapClassName?: string;
}) {
  const bodyPad =
    density === "compact"
      ? workspacePageBodyPaddingClass
      : "px-5 py-8 sm:px-8 sm:py-10";
  const bodyGap =
    density === "compact" ? workspacePageBodyGapClass : "gap-8 sm:gap-10";
  const stretchBody = density === "compact" || fillBody;

  return (
    <div className={cn("flex size-full min-w-0 flex-col", className)}>
      {header}
      <div
        className={cn(
          "min-w-0 flex-1 overflow-y-auto",
          stretchBody && "flex min-h-0 flex-col",
          density === "compact" && workspacePageScrollBodyClass,
          bodyClassName,
        )}
      >
        <div
          className={cn(
            "w-full min-w-0",
            density === "compact" ? "max-w-none" : "mx-auto max-w-[88rem]",
            bodyPad,
            stretchBody && "flex min-h-full flex-1 flex-col",
            contentClassName,
          )}
        >
          <div
            className={cn(
              "flex w-full min-w-0 flex-col",
              contentGapClassName ?? bodyGap,
              stretchBody && "min-h-full flex-1",
            )}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ShellHeader({
  backHref,
  title,
  description,
  descriptionSuffix,
  stat,
  actions,
  toolbar,
  toolbarClassName,
  className,
}: {
  backHref?: string;
  title: string;
  description?: string;
  descriptionSuffix?: ReactNode;
  stat?: string;
  actions?: ReactNode;
  toolbar?: ReactNode;
  toolbarClassName?: string;
  className?: string;
}) {
  const { t } = useI18n();
  const showTools = Boolean(toolbar ?? actions);

  return (
    <div
      className={cn(
        workspaceGlassHeaderClass,
        workspacePageInsetXClass,
        className,
      )}
    >
      <div className={cn("flex flex-col gap-1", workspacePageHeaderStripClass)}>
        <div className="flex min-w-0 items-center justify-between gap-2 sm:gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {backHref ? (
              <Button
                asChild
                size="icon-sm"
                variant="ghost"
                className="text-muted-foreground hover:text-foreground -ml-1 shrink-0"
              >
                <Link href={backHref}>
                  <ArrowLeftIcon className="size-4" />
                  <span className="sr-only">{t.common.back}</span>
                </Link>
              </Button>
            ) : (
              <div className={workspaceHeaderAccentClass} aria-hidden />
            )}
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <h1 className="shrink-0 text-base font-semibold tracking-tight sm:text-lg">
                {title}
              </h1>
              {stat ? (
                <span className="text-muted-foreground shrink-0 text-xs font-normal">
                  {stat}
                </span>
              ) : null}
              {description || descriptionSuffix ? (
                <div className="text-muted-foreground hidden max-w-xl min-w-0 items-center gap-2 text-xs leading-snug sm:flex">
                  {description ? (
                    <p className="min-w-0 truncate">{description}</p>
                  ) : null}
                  {description && descriptionSuffix ? (
                    <span
                      className="bg-border/70 h-3 w-px shrink-0"
                      aria-hidden
                    />
                  ) : null}
                  {descriptionSuffix ? (
                    <div className="min-w-0 shrink truncate">
                      {descriptionSuffix}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
          {showTools ? (
            <div className="flex shrink-0 items-center gap-2">
              {toolbar ? (
                <div
                  className={cn(
                    "hidden min-w-0 sm:block sm:w-40 md:w-48 lg:w-52",
                    toolbarClassName,
                  )}
                >
                  {toolbar}
                </div>
              ) : null}
              {actions}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function SplitView({
  primary,
  secondary,
  className,
  primaryClassName,
  secondaryClassName,
}: {
  primary: ReactNode;
  secondary: ReactNode;
  className?: string;
  primaryClassName?: string;
  secondaryClassName?: string;
}) {
  return (
    <div
      className={cn(
        "grid min-w-0 gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]",
        className,
      )}
    >
      <div className={cn("min-w-0 lg:sticky lg:top-6", primaryClassName)}>
        {primary}
      </div>
      <div className={cn("min-w-0", secondaryClassName)}>{secondary}</div>
    </div>
  );
}
