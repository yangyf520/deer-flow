"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { DialogSlotField } from "./dialogs";
import { dialogFieldControlClass } from "./styles";

export type NumberInputProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  layout?: "dialog" | "inline";
  inputClassName?: string;
  className?: string;
};

export function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  disabled,
  layout = "dialog",
  inputClassName,
  className,
}: NumberInputProps) {
  const input = (
    <Input
      type="number"
      min={min}
      max={max}
      step={step}
      className={cn(
        dialogFieldControlClass,
        layout === "inline" ? "w-16" : "w-full",
        inputClassName,
      )}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    />
  );

  if (layout === "inline") {
    return (
      <label
        className={cn(
          "text-muted-foreground flex items-center gap-2 text-sm",
          className,
        )}
      >
        {label}
        {input}
      </label>
    );
  }

  return (
    <DialogSlotField label={label} fieldClassName={className}>
      {input}
    </DialogSlotField>
  );
}
