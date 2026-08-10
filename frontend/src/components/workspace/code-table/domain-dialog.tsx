"use client";

import { useEffect, useState } from "react";

import {
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  FormDialog,
  dialogSaveFooterProps,
} from "@/components/component";
import type { CodeTableDomainSummary } from "@/core/code-table/api";
import { KNOWLEDGE_CODE_TABLE_DOMAIN } from "@/core/code-table/api";
import { useI18n } from "@/core/i18n/hooks";

type DomainFormValues = {
  domain: string;
  type_key: string;
  label: string;
};

interface CodeTableDomainCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  onConfirm: (input: DomainFormValues) => void | Promise<void>;
}

export function CodeTableDomainCreateDialog({
  open,
  onOpenChange,
  busy,
  onConfirm,
}: CodeTableDomainCreateDialogProps) {
  const { t } = useI18n();
  const ct = t.codeTable;
  const [domain, setDomain] = useState("");
  const [typeKey, setTypeKey] = useState("");
  const [label, setLabel] = useState("");

  useEffect(() => {
    if (!open) return;
    setDomain("");
    setTypeKey("");
    setLabel("");
  }, [open]);

  const canSave = domain.trim().length > 0 && typeKey.trim().length > 0;

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={ct.createDomain}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !canSave,
      })}
      onConfirm={() => {
        void onConfirm({
          domain: domain.trim(),
          type_key: typeKey.trim(),
          label: label.trim(),
        });
      }}
    >
      <DialogFormSection title={ct.sectionBasic}>
        <DialogFieldGrid>
          <DialogInputField
            label={ct.domainField}
            value={domain}
            onChange={setDomain}
            placeholder={ct.domainFieldPlaceholder}
            disabled={busy}
            autoCapitalize="none"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
          />
          <DialogInputField
            label={ct.typeKeyField}
            value={typeKey}
            onChange={setTypeKey}
            placeholder={ct.typeKeyFieldPlaceholder}
            disabled={busy}
            autoCapitalize="none"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
          />
          <DialogInputField
            label={ct.domainLabelField}
            value={label}
            onChange={setLabel}
            placeholder={ct.domainLabelPlaceholder}
            disabled={busy}
          />
        </DialogFieldGrid>
      </DialogFormSection>
    </FormDialog>
  );
}

interface CodeTableDomainEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target: CodeTableDomainSummary | null;
  busy: boolean;
  onConfirm: (input: {
    type_key: string;
    new_type_key?: string;
    label: string;
  }) => void | Promise<void>;
}

export function CodeTableDomainEditDialog({
  open,
  onOpenChange,
  target,
  busy,
  onConfirm,
}: CodeTableDomainEditDialogProps) {
  const { t } = useI18n();
  const ct = t.codeTable;
  const [typeKey, setTypeKey] = useState("");
  const [label, setLabel] = useState("");
  const entryCount = target?.entry_count ?? 0;
  const typeKeyLocked =
    target?.domain === KNOWLEDGE_CODE_TABLE_DOMAIN || entryCount > 0;
  const typeKeyHint = typeKeyLocked
    ? target?.domain === KNOWLEDGE_CODE_TABLE_DOMAIN
      ? ct.typeKeyReadonlyHint
      : ct.typeKeyInUseHint
    : ct.typeKeyFieldHint;

  useEffect(() => {
    if (!open || !target) return;
    setTypeKey(target.type_key);
    setLabel(target.label ?? "");
  }, [open, target]);

  const canSave = typeKey.trim().length > 0 && label.trim().length > 0;

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={ct.editDomain}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !canSave,
      })}
      onConfirm={() => {
        if (!target) return;
        const nextTypeKey = typeKey.trim();
        void onConfirm({
          type_key: target.type_key,
          new_type_key:
            nextTypeKey !== target.type_key ? nextTypeKey : undefined,
          label: label.trim(),
        });
      }}
    >
      {target ? (
        <DialogFormSection title={ct.sectionBasic}>
          <DialogFieldGrid>
            <DialogInputField
              label={ct.domainField}
              value={target.domain}
              onChange={() => undefined}
              disabled
              hint={ct.domainFieldReadonlyHint}
            />
            <DialogInputField
              label={ct.typeKeyField}
              value={typeKey}
              onChange={setTypeKey}
              placeholder={ct.typeKeyFieldPlaceholder}
              hint={typeKeyHint}
              disabled={busy || typeKeyLocked}
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
            />
            <DialogInputField
              label={ct.domainLabelField}
              value={label}
              onChange={setLabel}
              placeholder={ct.domainLabelPlaceholder}
              disabled={busy}
              autoFocus
            />
          </DialogFieldGrid>
        </DialogFormSection>
      ) : null}
    </FormDialog>
  );
}
