"use client";

import { useEffect, useState } from "react";

import {
  ConfirmDialog,
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogSelectField,
  DialogSlotField,
  FormDialog,
  dialogSaveFooterProps,
} from "@/components/component";
import { readOnlyFieldClass } from "@/components/component/styles";
import { useI18n } from "@/core/i18n/hooks";
import type { ScenarioPack, Space } from "@/core/knowledge";

export const SCENARIO_CODE_PATTERN = /^[a-z][a-z0-9-]*$/;

export function isValidScenarioCode(code: string): boolean {
  return SCENARIO_CODE_PATTERN.test(code.trim());
}

function ScenarioFormFields({
  code,
  setCode,
  label,
  setLabel,
  codeEditable,
  disabled,
  codeError,
  autoFocusLabel,
}: {
  code: string;
  setCode: (value: string) => void;
  label: string;
  setLabel: (value: string) => void;
  codeEditable: boolean;
  disabled?: boolean;
  codeError?: string;
  autoFocusLabel?: boolean;
}) {
  const { t } = useI18n();
  const kb = t.knowledge;

  return (
    <DialogFormSection title={kb.sectionBasic}>
      <DialogFieldGrid>
        <DialogInputField
          label={kb.catalogScenarioCode}
          value={code}
          onChange={setCode}
          placeholder={kb.catalogCodePlaceholder}
          disabled={disabled === true || !codeEditable}
          hint={codeEditable ? kb.catalogCodeHint : undefined}
          error={codeError}
          autoCapitalize="none"
          autoCorrect="off"
          autoComplete="off"
          spellCheck={false}
        />
        <DialogInputField
          label={kb.catalogFieldLabel}
          value={label}
          onChange={setLabel}
          placeholder={kb.catalogFieldLabelPlaceholder}
          disabled={disabled}
          autoFocus={autoFocusLabel}
        />
      </DialogFieldGrid>
    </DialogFormSection>
  );
}

interface ScenarioCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  onConfirm: (input: { code: string; label: string }) => void | Promise<void>;
}

export function ScenarioCreateDialog({
  open,
  onOpenChange,
  busy,
  onConfirm,
}: ScenarioCreateDialogProps) {
  const { t } = useI18n();
  const kb = t.knowledge;
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();

  useEffect(() => {
    if (!open) return;
    setCode("");
    setLabel("");
    setCodeError(undefined);
  }, [open]);

  const trimmedCode = code.trim();
  const trimmedLabel = label.trim();
  const validCode = trimmedCode.length > 0 && isValidScenarioCode(trimmedCode);

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={kb.createScenario}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !validCode || !trimmedLabel,
      })}
      onConfirm={() => {
        if (!validCode) {
          setCodeError(kb.catalogCodeInvalid);
          return;
        }
        void onConfirm({ code: trimmedCode, label: trimmedLabel });
      }}
    >
      <ScenarioFormFields
        code={code}
        setCode={(value) => {
          setCode(value);
          if (codeError) setCodeError(undefined);
        }}
        label={label}
        setLabel={setLabel}
        codeEditable
        disabled={busy}
        codeError={codeError}
        autoFocusLabel={false}
      />
    </FormDialog>
  );
}

interface ScenarioEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scenario: ScenarioPack | null;
  busy: boolean;
  deleteBusy?: boolean;
  onConfirm: (input: { label: string }) => void | Promise<void>;
  onDelete: () => void | Promise<void>;
}

export function ScenarioEditDialog({
  open,
  onOpenChange,
  scenario,
  busy,
  deleteBusy = false,
  onConfirm,
  onDelete,
}: ScenarioEditDialogProps) {
  const { t } = useI18n();
  const kb = t.knowledge;
  const [label, setLabel] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const pending = busy || deleteBusy;

  useEffect(() => {
    if (!open || !scenario) return;
    setLabel(scenario.label ?? scenario.type);
  }, [open, scenario]);

  return (
    <>
      <FormDialog
        open={open}
        onOpenChange={onOpenChange}
        title={kb.editScenario}
        {...dialogSaveFooterProps(t.common, {
          busy: pending,
          disabled: !label.trim(),
        })}
        onConfirm={() => {
          if (!scenario) return;
          void onConfirm({ label: label.trim() });
        }}
        leadingDestructive={{
          label: t.common.delete,
          onClick: () => setDeleteOpen(true),
          disabled: pending,
        }}
      >
        {scenario ? (
          <ScenarioFormFields
            code={scenario.type}
            setCode={() => undefined}
            label={label}
            setLabel={setLabel}
            codeEditable={false}
            disabled={pending}
            autoFocusLabel
          />
        ) : null}
      </FormDialog>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        description={kb.catalogDeleteConfirm}
        confirmLabel={deleteBusy ? t.common.loading : t.common.delete}
        confirmPending={deleteBusy}
        confirmVariant="destructive"
        onConfirm={async () => {
          await onDelete();
          setDeleteOpen(false);
        }}
        onCancel={() => setDeleteOpen(false)}
      />
    </>
  );
}

interface CatalogHostSwitchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spaces: Space[];
  currentHostId: string | null;
  busy: boolean;
  onConfirm: (hostSpaceId: string) => void | Promise<void>;
}

export function CatalogHostSwitchDialog({
  open,
  onOpenChange,
  spaces,
  currentHostId,
  busy,
  onConfirm,
}: CatalogHostSwitchDialogProps) {
  const { t } = useI18n();
  const kb = t.knowledge;
  const [targetId, setTargetId] = useState("");

  useEffect(() => {
    if (!open) return;
    const fallback =
      spaces.find((s) => s.id !== currentHostId)?.id ?? spaces[0]?.id ?? "";
    setTargetId(fallback);
  }, [currentHostId, open, spaces]);

  const currentSpace = spaces.find((s) => s.id === currentHostId);
  const currentName = currentSpace?.name?.trim();
  let currentLabel = "—";
  if (currentName) currentLabel = currentName;
  else if (currentHostId) currentLabel = currentHostId;

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={
        <>
          {kb.catalogMigrateHostTitle}
          <span className="text-muted-foreground ml-2 text-sm font-normal">
            {kb.catalogMigrateHostDescription}
          </span>
        </>
      }
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !targetId.trim() || targetId === currentHostId,
        saveLabel: kb.catalogSwitchSpace,
      })}
      onConfirm={() => {
        const next = targetId.trim();
        if (!next || next === currentHostId) return;
        void onConfirm(next);
      }}
    >
      <DialogFormSection>
        <DialogFieldGrid>
          {currentHostId ? (
            <DialogSlotField label={kb.catalogMigrateHostCurrentLabel}>
              <div className={readOnlyFieldClass}>{currentLabel}</div>
            </DialogSlotField>
          ) : null}
          <DialogSelectField
            label={kb.catalogMigrateHostSelect}
            value={targetId}
            onValueChange={setTargetId}
            disabled={busy || spaces.length === 0}
            placeholder={kb.catalogMigrateHostSelect}
            options={spaces.map((space) => ({
              value: space.id,
              label: space.name?.trim() || space.id,
            }))}
          />
        </DialogFieldGrid>
      </DialogFormSection>
    </FormDialog>
  );
}
