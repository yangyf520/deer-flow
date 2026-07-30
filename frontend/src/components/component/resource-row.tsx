"use client";

import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Settings-style row: primary column + trailing meta/actions. */
export function ResourceRow({
  title,
  description,
  meta,
  badges,
  actions,
  href,
  onClick,
  className,
  selected,
  "data-testid": dataTestId,
}: {
  title: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  href?: string;
  onClick?: () => void;
  className?: string;
  selected?: boolean;
  "data-testid"?: string;
}) {
  const interactive = Boolean(onClick ?? href);
  const Wrapper = href ? "a" : onClick ? "button" : "div";
  const wrapperProps = href
    ? { href }
    : onClick
      ? { type: "button" as const, onClick }
      : {};

  return (
    <Wrapper
      {...wrapperProps}
      data-testid={dataTestId}
      className={cn(
        "group/row flex w-full min-w-0 flex-col gap-3 rounded-xl px-4 py-3.5 text-left transition-colors sm:flex-row sm:items-center sm:gap-4",
        interactive &&
          "hover:bg-muted/50 focus-visible:ring-ring cursor-pointer focus-visible:ring-[3px] focus-visible:outline-none",
        selected && "bg-primary/5 ring-primary/20 ring-1",
        className,
      )}
    >
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <div className="truncate text-[15px] font-semibold tracking-tight">
            {title}
          </div>
          {badges}
        </div>
        {description ? (
          <p className="text-muted-foreground line-clamp-2 text-sm leading-snug">
            {description}
          </p>
        ) : null}
        {meta ? (
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs tabular-nums">
            {meta}
          </div>
        ) : null}
      </div>
      {actions ? (
        <div
          className="flex shrink-0 items-center gap-0.5 sm:ml-auto"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          {actions}
        </div>
      ) : null}
    </Wrapper>
  );
}

export function ResourceList({
  children,
  className,
  ...props
}: {
  children: ReactNode;
  className?: string;
} & ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "divide-border/60 flex flex-col divide-y px-1 py-1 sm:px-2",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
