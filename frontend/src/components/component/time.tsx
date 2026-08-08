"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { DialogSlotField } from "./dialogs";
import { dialogFieldControlClass } from "./styles";

/** Split a datetime-local value (`YYYY-MM-DDTHH:mm`) for separate pickers. */
export function splitLocalDateTime(local: string): {
  date: string;
  time: string;
} {
  const trimmed = local.trim();
  if (!trimmed) {
    return { date: "", time: "" };
  }
  const [datePart, timePart] = trimmed.split("T");
  return { date: datePart ?? "", time: (timePart ?? "").slice(0, 5) };
}

export function joinLocalDateTime(date: string, time: string): string {
  const datePart = date.trim();
  if (!datePart) {
    return "";
  }
  const timePart = (time.trim() || "00:00").slice(0, 5);
  return `${datePart}T${timePart}`;
}

export function dateInputLang(locale?: string): string | undefined {
  return locale === "zh-CN" ? "zh-CN" : undefined;
}

export type TimeInputProps = {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  locale?: string;
  className?: string;
  inputClassName?: string;
  "aria-label"?: string;
};

export function TimeInput({
  value,
  onChange,
  disabled,
  locale,
  className,
  inputClassName,
  "aria-label": ariaLabel,
}: TimeInputProps) {
  return (
    <Input
      type="time"
      lang={dateInputLang(locale)}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn(dialogFieldControlClass, className, inputClassName)}
    />
  );
}

export function DialogTimeField({
  label,
  fieldClassName,
  ...props
}: TimeInputProps & { label: string; fieldClassName?: string }) {
  return (
    <DialogSlotField label={label} fieldClassName={fieldClassName}>
      <TimeInput {...props} className={cn("w-full", props.className)} />
    </DialogSlotField>
  );
}
