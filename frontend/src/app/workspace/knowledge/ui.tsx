"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import {
  SPACE_ACCESS_VALUES,
  accessHint,
  accessLabel,
  kindLabel,
  scenarioLabel,
  type ScenarioPack,
  type SpaceAccessValue,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

export function PageShell({
  children,
  className,
  maxWidth = "5xl",
}: {
  children: React.ReactNode;
  className?: string;
  maxWidth?: "4xl" | "5xl";
}) {
  return (
    <div
      className={cn(
        "flex w-full flex-col gap-6 p-6",
        maxWidth === "4xl" ? "max-w-4xl" : "max-w-5xl",
        className,
      )}
    >
      {children}
    </div>
  );
}

function AccessOption({ value }: { value: SpaceAccessValue }) {
  const { t } = useI18n();
  const hint = accessHint(value, t.knowledge);
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-2 overflow-hidden">
      <span className="shrink-0">{accessLabel(value, t.knowledge)}</span>
      {hint ? (
        <span className="text-muted-foreground truncate text-xs">{hint}</span>
      ) : null}
    </span>
  );
}

function ScenarioOption({ s }: { s: ScenarioPack }) {
  const { t } = useI18n();
  const label = scenarioLabel(s.type, t.knowledge);
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-2 overflow-hidden">
      <span className="shrink-0">{label}</span>
      <span className="text-muted-foreground shrink-0 text-xs">{s.type}</span>
      <span className="text-muted-foreground min-w-0 truncate font-mono text-[11px] tabular-nums">
        k={s.top_k ?? "—"} · s={s.score ?? "—"}
      </span>
    </span>
  );
}

export { boundScenarioType } from "@/core/knowledge";

type AccessSelectProps = {
  value: string;
  onValueChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
  contentClassName?: string;
  contentAlign?: "start" | "center" | "end";
  placeholder?: string;
  size?: "sm" | "default";
};

export function AccessSelect({
  value,
  onValueChange,
  disabled,
  className,
  contentClassName,
  contentAlign,
  placeholder,
  size = "sm",
}: AccessSelectProps) {
  const { t } = useI18n();
  return (
    <Select value={value} disabled={disabled} onValueChange={onValueChange}>
      <SelectTrigger size={size} className={cn(className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent align={contentAlign} className={contentClassName}>
        {SPACE_ACCESS_VALUES.map((item) => (
          <SelectItem
            key={item}
            value={item}
            textValue={accessLabel(item, t.knowledge) ?? item}
          >
            <AccessOption value={item} />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type ScenarioSelectProps = {
  value?: string;
  onValueChange?: (value: string) => void;
  scenarios: ScenarioPack[];
  disabled?: boolean;
  readOnly?: boolean;
  className?: string;
  contentClassName?: string;
  placeholder?: string;
  inheritLabel?: string;
  inheritValue?: string;
  size?: "sm" | "default";
};

export function ScenarioSelect({
  value,
  onValueChange,
  scenarios,
  disabled,
  readOnly,
  className,
  contentClassName,
  placeholder,
  inheritLabel,
  inheritValue,
  size = "sm",
}: ScenarioSelectProps) {
  if (readOnly) {
    const selected = value
      ? scenarios.find((s) => s.type === value)
      : undefined;
    return (
      <div
        className={cn(
          "text-muted-foreground flex max-w-full min-w-0 items-center text-xs select-none",
          className,
        )}
        aria-readonly="true"
      >
        {selected ? (
          <ScenarioOption s={selected} />
        ) : (
          <span className="text-muted-foreground">{placeholder}</span>
        )}
      </div>
    );
  }

  return (
    <Select value={value} disabled={disabled} onValueChange={onValueChange}>
      <SelectTrigger size={size} className={cn(className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent
        className={cn(
          "min-w-[var(--radix-select-trigger-width)]",
          contentClassName,
        )}
      >
        {inheritLabel && inheritValue ? (
          <SelectItem value={inheritValue}>{inheritLabel}</SelectItem>
        ) : null}
        {scenarios.map((s) => (
          <SelectItem key={s.type} value={s.type}>
            <ScenarioOption s={s} />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type KindSelectProps = {
  value: string;
  onValueChange: (value: string) => void;
  kinds: Array<{ id: string }>;
  allValue?: string;
  allLabel: string;
  showId?: boolean;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
  size?: "sm" | "default";
};

export function KindSelect({
  value,
  onValueChange,
  kinds,
  allValue = "__all__",
  allLabel,
  showId = false,
  disabled,
  className,
  placeholder,
  size = "sm",
}: KindSelectProps) {
  const { t } = useI18n();
  return (
    <Select value={value} disabled={disabled} onValueChange={onValueChange}>
      <SelectTrigger size={size} className={cn(className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={allValue}>{allLabel}</SelectItem>
        {kinds.map((k) => (
          <SelectItem key={k.id} value={k.id}>
            {kindLabel(k.id, t.knowledge)}
            {showId ? (
              <span className="text-muted-foreground ml-2 font-mono text-[10px]">
                {k.id}
              </span>
            ) : null}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
