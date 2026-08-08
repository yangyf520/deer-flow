"use client";

import { Toggle } from "@/components/component";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import {
  SPACE_ACCESS_VALUES,
  accessHint,
  accessLabel,
  scenarioLabel,
  tagGroupLabel,
  type ScenarioPack,
  type SpaceAccessValue,
  type TagGroupEntry,
  type TagGroupId,
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
  const label = scenarioLabel(s.type, t.knowledge, s);
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-2 overflow-hidden">
      <span className="shrink-0">{label}</span>
      <span className="text-muted-foreground shrink-0 font-mono text-xs">
        {s.type}
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

export type UploadMode = "unstructured" | "structured";

export function uploadModeToggleItems(knowledge: Translations["knowledge"]) {
  return [
    {
      value: "unstructured",
      label: knowledge.uploadModeUnstructured,
    },
    {
      value: "structured",
      label: knowledge.uploadModeStructured,
    },
  ];
}

type UploadModeToggleProps = {
  value: UploadMode;
  onValueChange: (value: UploadMode) => void;
  disabled?: boolean;
  className?: string;
  scrollable?: boolean;
};

export function UploadModeToggle({
  value,
  onValueChange,
  disabled,
  className,
  scrollable = true,
}: UploadModeToggleProps) {
  const { t } = useI18n();
  return (
    <Toggle
      value={value}
      onValueChange={(next) => onValueChange(next as UploadMode)}
      items={uploadModeToggleItems(t.knowledge)}
      disabled={disabled}
      scrollable={scrollable}
      className={className}
    />
  );
}

export function policyTagToggleItems(
  knowledge: Translations["knowledge"],
  tagGroups: TagGroupEntry[],
) {
  return tagGroups.map((group) => ({
    value: group.id,
    label: tagGroupLabel(group.id, knowledge, group),
  }));
}

type PolicyTagToggleProps = {
  value: TagGroupId[];
  onValueChange: (value: TagGroupId[]) => void;
  tagGroups: TagGroupEntry[];
  disabled?: boolean;
  className?: string;
  scrollable?: boolean;
};

export function PolicyTagToggle({
  value,
  onValueChange,
  tagGroups,
  disabled,
  className,
  scrollable = true,
}: PolicyTagToggleProps) {
  const { t } = useI18n();
  return (
    <Toggle
      type="multiple"
      value={value}
      onValueChange={(next) => onValueChange(next)}
      items={policyTagToggleItems(t.knowledge, tagGroups)}
      disabled={disabled}
      scrollable={scrollable}
      className={className}
    />
  );
}
