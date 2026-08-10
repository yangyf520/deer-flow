"use client";

import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { forwardRef } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import {
  itemCardBadgeClass,
  itemCardIconClass,
  itemCardIconToneClass,
  panelInteractiveClass,
  rowActionIconProps,
} from "./styles";
import { Tooltip } from "./tooltip";

const metaPillVariantClass = {
  tag: "rounded-sm border border-border/50 bg-muted/20 dark:border-white/12 dark:bg-muted/30 dark:text-foreground/80",
  plain: "bg-transparent px-0 py-0 dark:ring-0",
} as const;

const metaPillSizeClass = {
  default: "px-2 py-0.5 text-xs leading-snug",
  sm: "h-5 shrink-0 px-1.5 py-0 text-[10px] leading-none whitespace-nowrap",
  row: "h-5 min-h-5 shrink-0 items-center px-1.5 py-0 text-[10px] font-normal leading-none whitespace-nowrap",
} as const;

export const itemRowMetaChipClass =
  "inline-flex h-5 min-h-5 shrink-0 items-center px-1.5 text-[10px] font-normal leading-none";

export const itemRowStatusBadgeClass = cn(itemRowMetaChipClass, "rounded-full");

export type ItemRowStatusTone =
  | "success"
  | "warning"
  | "info"
  | "primary"
  | "danger"
  | "neutral"
  | "muted";

export const itemRowStatusToneClass: Record<ItemRowStatusTone, string> = {
  success:
    "border-emerald-500/35 bg-emerald-500/12 text-emerald-800 dark:text-emerald-200",
  warning:
    "border-amber-500/35 bg-amber-500/12 text-amber-900 dark:text-amber-200",
  info: "border-sky-500/35 bg-sky-500/12 text-sky-900 dark:text-sky-200",
  primary: "border-sky-500/35 bg-sky-500/12 text-sky-900 dark:text-sky-200",
  danger:
    "border-destructive/45 bg-destructive/12 text-destructive dark:text-red-300",
  neutral: "border-border/60 bg-muted/45 text-foreground",
  muted:
    "border-border/50 bg-muted/25 text-muted-foreground dark:text-muted-foreground",
};

const itemRowStatusSuccessValues = new Set([
  "ready",
  "success",
  "enabled",
  "active",
  "completed",
  "done",
  "ok",
]);

const itemRowStatusWarningValues = new Set([
  "processing",
  "pending",
  "queued",
  "running",
  "paused",
  "in_progress",
  "embedding",
  "parsing",
  "warning",
]);

const itemRowStatusDangerValues = new Set(["failed", "error", "interrupted"]);

/** Map lifecycle / workflow status strings to list row badge tones. */
export function itemRowStatusToneFromValue(status: string): ItemRowStatusTone {
  const key = status.trim().toLowerCase();
  if (itemRowStatusSuccessValues.has(key)) {
    return "success";
  }
  if (itemRowStatusDangerValues.has(key)) {
    return "danger";
  }
  if (itemRowStatusWarningValues.has(key)) {
    return "warning";
  }
  return "neutral";
}

/** Mask sensitive strings as `{prefix}{start}*{end}` (e.g. tokens, key prefixes). */
export function maskMiddle(
  value: string,
  {
    start = 7,
    end = 8,
    mask = "*",
    leadingPrefix = "",
  }: {
    start?: number;
    end?: number;
    mask?: string;
    leadingPrefix?: string;
  } = {},
): string {
  if (mask.length > 0 && value.includes(mask)) {
    return value;
  }
  const normalized = value.endsWith("…") ? value.slice(0, -1) : value;
  const prefix =
    leadingPrefix && normalized.startsWith(leadingPrefix) ? leadingPrefix : "";
  const body = prefix ? normalized.slice(prefix.length) : normalized;
  if (body.length <= start || body.length <= start + end) {
    return normalized;
  }
  return `${prefix}${body.slice(0, start)}${mask}${body.slice(-end)}`;
}

/** Mask API key for display: fixed `dfk_{6}*{6}` width on the secret body. */
export function formatApiKeyPrefixDisplay(
  value: string,
  {
    leadingPrefix = "dfk_",
    start = 6,
    end = 6,
    mask = "*",
    placeholder = "·",
  }: {
    leadingPrefix?: string;
    start?: number;
    end?: number;
    mask?: string;
    placeholder?: string;
  } = {},
): string {
  if (mask.length > 0 && value.includes(mask)) {
    return value;
  }

  const normalized = value.endsWith("…") ? value.slice(0, -1) : value;
  const prefix =
    leadingPrefix && normalized.startsWith(leadingPrefix) ? leadingPrefix : "";
  const body = prefix ? normalized.slice(prefix.length) : normalized;
  if (!body) {
    return normalized;
  }

  const head = body.slice(0, start).padEnd(start, placeholder);
  const tail =
    body.length >= start + end ? body.slice(-end) : placeholder.repeat(end);
  return `${prefix}${head}${mask}${tail}`;
}

export function ItemRowStatusBadge({
  className,
  variant = "outline",
  tone,
  ...props
}: ComponentProps<typeof Badge> & { tone?: ItemRowStatusTone }) {
  return (
    <Badge
      variant={variant}
      className={cn(
        itemRowStatusBadgeClass,
        tone && itemRowStatusToneClass[tone],
        className,
      )}
      {...props}
    />
  );
}

export const MetaPill = forwardRef<
  HTMLSpanElement,
  {
    children: ReactNode;
    className?: string;
    variant?: keyof typeof metaPillVariantClass;
    size?: keyof typeof metaPillSizeClass;
    hint?: string;
    mono?: boolean;
  }
>(function MetaPill(
  {
    children,
    className,
    variant = "tag",
    size = "default",
    hint,
    mono = false,
  },
  ref,
) {
  const pill = (
    <span
      ref={ref}
      className={cn(
        "text-muted-foreground inline-flex max-w-full items-center gap-1 tracking-tight",
        mono && "font-mono",
        size === "default" && "text-xs leading-snug",
        variant === "tag" && size === "default"
          ? "break-words whitespace-normal"
          : "truncate whitespace-nowrap",
        variant === "tag"
          ? metaPillVariantClass.tag
          : metaPillVariantClass.plain,
        metaPillSizeClass[size],
        className,
      )}
    >
      {children}
    </span>
  );

  if (hint) {
    return (
      <Tooltip
        content={<span className="block max-w-xs text-balance">{hint}</span>}
        delayDuration={0}
      >
        {pill}
      </Tooltip>
    );
  }

  return pill;
});
MetaPill.displayName = "MetaPill";

export function ItemRowTag({
  children,
  className,
  hint,
}: {
  children: ReactNode;
  className?: string;
  hint?: string;
}) {
  return (
    <MetaPill size="row" className={className} hint={hint}>
      {children}
    </MetaPill>
  );
}

export type ItemCardIconTone = keyof typeof itemCardIconToneClass;

export function ItemCardIcon({
  icon: Icon,
  tone = "neutral",
}: {
  icon: LucideIcon;
  tone?: ItemCardIconTone;
}) {
  return (
    <div className={cn(itemCardIconToneClass[tone])} aria-hidden>
      <Icon className={itemCardIconClass} strokeWidth={2} />
    </div>
  );
}

export function ItemCardBadge({
  children,
  variant = "secondary",
}: {
  children: ReactNode;
  variant?: "default" | "secondary" | "destructive" | "outline";
}) {
  return (
    <Badge variant={variant} className={itemCardBadgeClass}>
      {children}
    </Badge>
  );
}

export function itemMetaTags(
  items: Array<{
    key: string;
    label: ReactNode;
    hint?: string;
    className?: string;
  }>,
): ReactNode[] {
  return items.map(({ key, label, hint, className }) => (
    <MetaPill key={key} mono hint={hint} className={className}>
      {label}
    </MetaPill>
  ));
}

export function formatWorkspaceItemTimestamp(
  value: string,
  locale: string,
): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function ItemCard({
  href,
  icon,
  iconTone = "neutral",
  title,
  description,
  badges,
  metaTags,
  metaTagsLayout = "inline",
  actions,
  className,
}: {
  href?: string;
  icon: LucideIcon;
  iconTone?: ItemCardIconTone;
  title: ReactNode;
  description?: ReactNode;
  badges?: ReactNode;
  metaTags?: ReactNode[];
  metaTagsLayout?:
    | "inline"
    | "inline-nowrap"
    | "inline-grow-leading"
    | "stacked";
  actions?: ReactNode;
  className?: string;
}) {
  const hasMetaTags = Boolean(metaTags?.length);

  const body = (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2.5">
        <ItemCardIcon icon={icon} tone={iconTone} />
        <div className="min-w-0 space-y-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
            <h3 className="min-w-0 flex-1 truncate text-xs leading-snug font-semibold tracking-tight">
              {title}
            </h3>
            {badges}
          </div>
          {description ? (
            typeof description === "string" ? (
              <Tooltip
                content={description}
                contentClassName="max-w-[16rem] px-2 py-1 text-[11px] leading-snug whitespace-normal break-words [text-wrap:wrap]"
              >
                <p className="text-muted-foreground truncate text-xs leading-relaxed">
                  {description}
                </p>
              </Tooltip>
            ) : (
              <p className="text-muted-foreground truncate text-xs leading-relaxed">
                {description}
              </p>
            )
          ) : null}
        </div>
      </div>
      {hasMetaTags ? (
        <div className="mt-1.5">
          <ul
            className={cn(
              "flex",
              metaTagsLayout === "stacked"
                ? "flex-col gap-1.5"
                : metaTagsLayout === "inline-nowrap" ||
                    metaTagsLayout === "inline-grow-leading"
                  ? "min-h-[1.625rem] flex-nowrap gap-1"
                  : "min-h-[1.625rem] flex-wrap gap-1",
            )}
          >
            {metaTags!.map((item, i) => (
              <li
                key={i}
                className={cn(
                  "max-w-full min-w-0",
                  metaTagsLayout === "stacked" && "w-full",
                  metaTagsLayout === "inline-nowrap" &&
                    "w-[calc((100%-0.375rem)/2)] flex-none shrink-0",
                  metaTagsLayout === "inline-grow-leading" &&
                    (i < metaTags!.length - 1
                      ? "min-w-0 shrink overflow-hidden"
                      : "flex-none shrink-0"),
                )}
              >
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );

  return (
    <article
      className={cn(
        panelInteractiveClass,
        "group/card flex w-full flex-col",
        className,
      )}
    >
      {href ? (
        <Link
          href={href}
          className="focus-visible:ring-ring hover:bg-muted/25 flex min-h-0 flex-1 flex-col rounded-[inherit] px-3.5 py-2.5 transition-colors outline-none focus-visible:ring-[3px]"
        >
          {body}
        </Link>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col px-3.5 py-2.5">{body}</div>
      )}
      {actions ? (
        <div
          className="border-border/40 bg-muted/10 dark:bg-muted/20 flex min-w-0 flex-nowrap items-stretch gap-1.5 border-t px-2 py-2"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          {actions}
        </div>
      ) : null}
    </article>
  );
}

export type ItemGridCols = 1 | 2 | 3 | 4;

export const DEFAULT_ITEM_GRID_COLS = 4 satisfies ItemGridCols;

const colsClass: Record<ItemGridCols, string> = {
  1: "grid-cols-1",
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3",
  4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
};

/** Collapse empty tracks so a few cards grow to fill the row (auto-fit), not fixed N cols. */
const denseGridClass =
  "grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))]";

export const itemGridClass = colsClass[DEFAULT_ITEM_GRID_COLS];

export function ItemGrid({
  children,
  cols = DEFAULT_ITEM_GRID_COLS,
  density = "default",
  className,
}: {
  children: ReactNode;
  cols?: ItemGridCols;
  density?: "default" | "dense";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid w-full min-w-0",
        density === "dense"
          ? cn("gap-2", denseGridClass)
          : cn("gap-3", colsClass[cols]),
        className,
      )}
    >
      {children}
    </div>
  );
}

export const cardActionClass = cn(
  "inline-flex cursor-pointer items-center justify-center whitespace-nowrap font-medium transition-colors",
  "outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
  "disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50",
  "[&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 [&_svg]:shrink-0",
  "h-7 min-h-7 shrink-0 gap-1 rounded-md border border-border/70 bg-background px-2.5 text-xs leading-none shadow-none sm:px-3",
  "hover:bg-accent/25 hover:text-accent-foreground active:bg-accent/35",
  "dark:border-white/10 dark:bg-background/60 dark:hover:bg-accent/30 dark:active:bg-accent/40",
  "[&_svg]:size-3",
);

type CardActionBase = {
  icon: LucideIcon;
  label: string;
  tooltip?: string;
  className?: string;
  disabled?: boolean;
};

type CardActionLinkProps = CardActionBase & {
  href: string;
  onClick?: never;
  type?: never;
};

type CardActionButtonProps = CardActionBase &
  Pick<ComponentProps<"button">, "onClick" | "type"> & {
    href?: never;
  };

function maybeTooltip(node: ReactNode, tooltip?: string) {
  if (!tooltip) {
    return node;
  }
  return <Tooltip content={tooltip}>{node}</Tooltip>;
}

export function CardAction(props: CardActionLinkProps | CardActionButtonProps) {
  const { icon: Icon, label, tooltip, className, disabled } = props;
  const btnClass = cn(cardActionClass, className);

  if ("href" in props && props.href) {
    return maybeTooltip(
      <Link
        href={props.href}
        className={btnClass}
        aria-disabled={disabled ? true : undefined}
        tabIndex={disabled ? -1 : undefined}
      >
        <Icon {...rowActionIconProps} />
        {label}
      </Link>,
      tooltip,
    );
  }

  return maybeTooltip(
    <button
      type={props.type ?? "button"}
      className={btnClass}
      disabled={disabled}
      onClick={props.onClick}
    >
      <Icon {...rowActionIconProps} />
      {label}
    </button>,
    tooltip,
  );
}
