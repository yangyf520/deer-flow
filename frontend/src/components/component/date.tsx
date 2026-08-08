"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { DialogSlotField } from "./dialogs";
import { dialogFieldControlClass } from "./styles";
import { dateInputLang } from "./time";

export type DateInputProps = {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  locale?: string;
  className?: string;
  inputClassName?: string;
  "aria-label"?: string;
};

export function DateInput({
  value,
  onChange,
  disabled,
  locale,
  className,
  inputClassName,
  "aria-label": ariaLabel,
}: DateInputProps) {
  return (
    <Input
      type="date"
      lang={dateInputLang(locale)}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn(dialogFieldControlClass, className, inputClassName)}
    />
  );
}

export function DialogDateField({
  label,
  fieldClassName,
  ...props
}: DateInputProps & { label: string; fieldClassName?: string }) {
  return (
    <DialogSlotField label={label} fieldClassName={fieldClassName}>
      <DateInput {...props} className={cn("w-full", props.className)} />
    </DialogSlotField>
  );
}
