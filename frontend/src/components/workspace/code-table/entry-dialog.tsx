"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  ConfirmDialog,
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogTextareaField,
  FormDialog,
  dialogSaveFooterProps,
} from "@/components/component";
import {
  createCodeTableDomain,
  createCodeTableEntry,
  DEFAULT_CODE_TABLE_TYPE_KEY,
} from "@/core/code-table/api";
import {
  attrsFromFormValues,
  codeTableEntryAttrFields,
  formatListField,
  parseListField,
  readStringListAttr,
  type CodeTableAttrFieldSpec,
  type CodeTableEntryFormValues,
  type CodeTableEntryRecord,
} from "@/core/code-table/entry-schema";
import { useI18n } from "@/core/i18n/hooks";

const EMPTY_ATTR_FIELDS: CodeTableAttrFieldSpec[] = [];

type EntryDialogCopy = {
  createTitle: string;
  editTitle: string;
  sectionBasic: string;
  sectionAttrs: string;
  entryCode: string;
  entryLabel: string;
  entryCodePlaceholder?: string;
  entryLabelPlaceholder?: string;
  entryCodeHint?: string;
  deleteConfirm: string;
};

function useEntryDialogCopy(): EntryDialogCopy {
  const ct = useI18n().t.codeTable;
  return {
    createTitle: ct.createEntry,
    editTitle: ct.editEntry,
    sectionBasic: ct.sectionBasic,
    sectionAttrs: ct.sectionAttrs,
    entryCode: ct.entryCode,
    entryLabel: ct.entryLabel,
    entryCodePlaceholder: ct.entryCodePlaceholder,
    entryLabelPlaceholder: ct.entryLabelPlaceholder,
    entryCodeHint: ct.entryCodeHint,
    deleteConfirm: ct.deleteEntryConfirm,
  };
}

function CodeTableEntryFormFields({
  copy,
  code,
  setCode,
  label,
  setLabel,
  attrFields,
  attrTexts,
  setAttrText,
  codeEditable,
  disabled,
  autoFocusLabel,
  domainField,
}: {
  copy: EntryDialogCopy;
  code: string;
  setCode: (value: string) => void;
  label: string;
  setLabel: (value: string) => void;
  attrFields: CodeTableAttrFieldSpec[];
  attrTexts: Record<string, string>;
  setAttrText: (key: string, value: string) => void;
  codeEditable: boolean;
  disabled?: boolean;
  autoFocusLabel?: boolean;
  domainField?: {
    label: string;
    placeholder?: string;
    hint?: string;
    value: string;
    onChange: (value: string) => void;
    readOnly?: boolean;
  };
}) {
  const codePlaceholder = codeEditable
    ? (copy.entryCodeHint ?? copy.entryCodePlaceholder)
    : copy.entryCodePlaceholder;

  return (
    <>
      <DialogFormSection title={copy.sectionBasic}>
        <DialogFieldGrid>
          {domainField ? (
            <DialogInputField
              label={domainField.label}
              value={domainField.value}
              onChange={
                domainField.readOnly ? () => undefined : domainField.onChange
              }
              placeholder={domainField.placeholder}
              hint={domainField.hint}
              disabled={Boolean(disabled) || domainField.readOnly}
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
            />
          ) : null}
          <DialogInputField
            label={copy.entryCode}
            value={code}
            onChange={setCode}
            placeholder={codePlaceholder}
            disabled={disabled === true || !codeEditable}
            autoCapitalize="none"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
          />
          <DialogInputField
            label={copy.entryLabel}
            value={label}
            onChange={setLabel}
            placeholder={copy.entryLabelPlaceholder}
            disabled={disabled}
            autoFocus={autoFocusLabel}
          />
        </DialogFieldGrid>
      </DialogFormSection>

      {attrFields.length > 0 ? (
        <DialogFormSection title={copy.sectionAttrs}>
          <DialogFieldGrid>
            {attrFields.map((field) => (
              <DialogTextareaField
                key={field.attrKey}
                label={field.label}
                value={attrTexts[field.attrKey] ?? ""}
                onChange={(value) => setAttrText(field.attrKey, value)}
                placeholder={
                  field.hint && field.placeholder
                    ? `${field.hint}\n${field.placeholder}`
                    : (field.hint ?? field.placeholder)
                }
                disabled={disabled}
                rows={field.rows ?? 2}
              />
            ))}
          </DialogFieldGrid>
        </DialogFormSection>
      ) : null}
    </>
  );
}

function buildFormValues(
  code: string,
  label: string,
  attrFields: CodeTableAttrFieldSpec[],
  attrTexts: Record<string, string>,
): CodeTableEntryFormValues {
  const attrs: Record<string, string[]> = {};
  for (const field of attrFields) {
    attrs[field.attrKey] = parseListField(attrTexts[field.attrKey] ?? "");
  }
  return {
    code: code.trim(),
    label: label.trim(),
    attrs,
  };
}

interface CodeTableEntryCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  title?: string;
  attrFields?: CodeTableAttrFieldSpec[];
  domainField?: {
    label: string;
    placeholder?: string;
    hint?: string;
    value: string;
    onChange: (value: string) => void;
    readOnly?: boolean;
  };
  onConfirm: (input: CodeTableEntryFormValues) => void | Promise<void>;
}

function CodeTableEntryCreateDialog({
  open,
  onOpenChange,
  busy,
  title,
  attrFields = EMPTY_ATTR_FIELDS,
  domainField,
  onConfirm,
}: CodeTableEntryCreateDialogProps) {
  const { t } = useI18n();
  const copy = useEntryDialogCopy();
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [attrTexts, setAttrTexts] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    setCode("");
    setLabel("");
    const next: Record<string, string> = {};
    for (const field of attrFields) next[field.attrKey] = "";
    setAttrTexts(next);
  }, [attrFields, open]);

  const canSave =
    code.trim().length > 0 &&
    label.trim().length > 0 &&
    (!domainField || domainField.value.trim().length > 0);

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title ?? copy.createTitle}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !canSave,
      })}
      onConfirm={() => {
        void onConfirm(buildFormValues(code, label, attrFields, attrTexts));
      }}
    >
      <CodeTableEntryFormFields
        copy={copy}
        code={code}
        setCode={setCode}
        label={label}
        setLabel={setLabel}
        attrFields={attrFields}
        attrTexts={attrTexts}
        setAttrText={(key, value) =>
          setAttrTexts((prev) => ({ ...prev, [key]: value }))
        }
        domainField={domainField}
        codeEditable
        disabled={busy}
      />
    </FormDialog>
  );
}

interface CodeTableEntryEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entry: CodeTableEntryRecord | null;
  busy: boolean;
  deleteBusy?: boolean;
  attrFields?: CodeTableAttrFieldSpec[];
  onConfirm: (
    input: Omit<CodeTableEntryFormValues, "code">,
  ) => void | Promise<void>;
  onDelete: () => void | Promise<void>;
}

export function CodeTableEntryEditDialog({
  open,
  onOpenChange,
  entry,
  busy,
  deleteBusy = false,
  attrFields = EMPTY_ATTR_FIELDS,
  onConfirm,
  onDelete,
}: CodeTableEntryEditDialogProps) {
  const { t } = useI18n();
  const copy = useEntryDialogCopy();
  const [label, setLabel] = useState("");
  const [attrTexts, setAttrTexts] = useState<Record<string, string>>({});
  const [deleteOpen, setDeleteOpen] = useState(false);
  const pending = busy || deleteBusy;

  useEffect(() => {
    if (!open || !entry) return;
    setLabel(entry.label);
    const next: Record<string, string> = {};
    for (const field of attrFields) {
      next[field.attrKey] = formatListField(
        readStringListAttr(entry.attrs, field.attrKey),
      );
    }
    setAttrTexts(next);
  }, [attrFields, entry, open]);

  const code = entry?.code ?? "";

  return (
    <>
      <FormDialog
        open={open}
        onOpenChange={onOpenChange}
        title={copy.editTitle}
        {...dialogSaveFooterProps(t.common, {
          busy: pending,
          disabled: !label.trim(),
        })}
        onConfirm={() => {
          if (!entry) return;
          const values = buildFormValues(code, label, attrFields, attrTexts);
          void onConfirm({
            label: values.label,
            attrs: attrsFromFormValues(values, attrFields),
          });
        }}
        leadingDestructive={{
          label: t.common.delete,
          onClick: () => setDeleteOpen(true),
          disabled: pending,
        }}
      >
        {entry ? (
          <CodeTableEntryFormFields
            copy={copy}
            code={code}
            setCode={() => undefined}
            label={label}
            setLabel={setLabel}
            attrFields={attrFields}
            attrTexts={attrTexts}
            setAttrText={(key, value) =>
              setAttrTexts((prev) => ({ ...prev, [key]: value }))
            }
            codeEditable={false}
            disabled={pending}
            autoFocusLabel
          />
        ) : null}
      </FormDialog>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        description={copy.deleteConfirm}
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

/** Unified create scope: root omits `domain`; detail passes a read-only domain. */
export type CodeTableCreateEntryScope = {
  domain?: string;
  typeKey?: string;
  parentCode?: string;
  attrFields?: CodeTableAttrFieldSpec[];
  onCreated?: (domain: string) => void | Promise<void>;
};

export function CodeTableCreateEntryDialog({
  open,
  onOpenChange,
  scope,
  onError,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scope: CodeTableCreateEntryScope;
  onError?: (error: Error) => void;
}) {
  const { t } = useI18n();
  const ct = t.codeTable;
  const [busy, setBusy] = useState(false);
  const [domainDraft, setDomainDraft] = useState("");

  const fixedDomain = scope.domain?.trim() ?? "";
  const domainValue = fixedDomain.length > 0 ? fixedDomain : domainDraft;
  const isEntryCreate = fixedDomain.length > 0;
  const trimmedTypeKey = scope.typeKey?.trim();
  const resolvedTypeKey = trimmedTypeKey ?? DEFAULT_CODE_TABLE_TYPE_KEY;
  const attrFields = scope.attrFields ?? codeTableEntryAttrFields(ct);

  async function handleConfirm(input: CodeTableEntryFormValues) {
    setBusy(true);
    try {
      if (isEntryCreate) {
        await createCodeTableEntry(fixedDomain, {
          type_key: resolvedTypeKey,
          code: input.code,
          label: input.label,
          parent_code: scope.parentCode ?? "",
          attrs: attrsFromFormValues(input, attrFields),
        });
        onOpenChange(false);
        toast.success(ct.entryCreated);
        await scope.onCreated?.(fixedDomain);
        return;
      }

      const created = await createCodeTableDomain({
        domain: domainDraft.trim(),
        code: input.code,
        label: input.label,
        attrs: attrsFromFormValues(input, attrFields),
      });
      onOpenChange(false);
      setDomainDraft("");
      toast.success(ct.domainCreated);
      await scope.onCreated?.(created.domain);
    } catch (e) {
      onError?.(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <CodeTableEntryCreateDialog
      open={open}
      onOpenChange={(nextOpen) => {
        onOpenChange(nextOpen);
        if (!nextOpen) setDomainDraft("");
      }}
      busy={busy}
      attrFields={attrFields}
      domainField={{
        label: ct.domainField,
        placeholder: ct.domainFieldPlaceholder,
        hint: isEntryCreate ? ct.domainFieldReadonlyHint : ct.domainFieldHint,
        value: domainValue,
        onChange: setDomainDraft,
        readOnly: isEntryCreate,
      }}
      onConfirm={handleConfirm}
    />
  );
}
