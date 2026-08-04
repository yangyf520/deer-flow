"use client";

import { useState } from "react";

import {
  AccessSelect,
  UploadModeToggle,
  type UploadMode,
} from "@/app/workspace/knowledge/ui";
import {
  ConfirmDialog,
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogSlotField,
  FormDialog,
  dialogSaveFooterProps,
} from "@/components/component";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import type { Space } from "@/core/knowledge";
import { buildSpaceEditMeta } from "@/core/knowledge";

function SpaceFormFields({
  name,
  setName,
  description,
  setDescription,
  access,
  setAccess,
  ingestMode,
  setIngestMode,
  topK,
  setTopK,
  score,
  setScore,
  disabled,
  nameAutoFocus,
}: {
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  access: string;
  setAccess: (v: string) => void;
  ingestMode: UploadMode;
  setIngestMode: (v: UploadMode) => void;
  topK: string;
  setTopK: (v: string) => void;
  score: string;
  setScore: (v: string) => void;
  disabled?: boolean;
  nameAutoFocus?: boolean;
}) {
  const { t } = useI18n();

  return (
    <DialogFormSection title={t.knowledge.sectionBasic}>
      <DialogFieldGrid>
        <DialogInputField
          label={t.knowledge.fieldName}
          value={name}
          onChange={setName}
          placeholder={t.knowledge.namePlaceholder}
          disabled={disabled}
          autoFocus={nameAutoFocus}
        />
        <DialogInputField
          label={t.knowledge.fieldDescription}
          value={description}
          onChange={setDescription}
          placeholder={t.knowledge.descriptionPlaceholder}
          disabled={disabled}
        />
        <DialogSlotField label={t.knowledge.fieldAccess}>
          <AccessSelect
            value={access}
            onValueChange={setAccess}
            disabled={disabled}
            className="w-full"
          />
        </DialogSlotField>
        <DialogSlotField label={t.knowledge.uploadModeLabel}>
          <UploadModeToggle
            value={ingestMode}
            onValueChange={setIngestMode}
            disabled={disabled}
            className="w-full"
          />
        </DialogSlotField>
        <DialogSlotField label={t.knowledge.fieldTopK}>
          <Input
            type="number"
            min={1}
            max={50}
            step={1}
            className="h-9 w-full"
            value={topK}
            onChange={(e) => setTopK(e.target.value)}
            disabled={disabled}
          />
        </DialogSlotField>
        <DialogSlotField label={t.knowledge.fieldScore}>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.01}
            className="h-9 w-full"
            value={score}
            onChange={(e) => setScore(e.target.value)}
            disabled={disabled}
          />
        </DialogSlotField>
      </DialogFieldGrid>
    </DialogFormSection>
  );
}

interface SpaceCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  access: string;
  setAccess: (v: string) => void;
  ingestMode: UploadMode;
  setIngestMode: (v: UploadMode) => void;
  topK: string;
  setTopK: (v: string) => void;
  score: string;
  setScore: (v: string) => void;
  busy: boolean;
  onConfirm: () => void;
}

export function SpaceCreateDialog({
  open,
  onOpenChange,
  name,
  setName,
  description,
  setDescription,
  access,
  setAccess,
  ingestMode,
  setIngestMode,
  topK,
  setTopK,
  score,
  setScore,
  busy,
  onConfirm,
}: SpaceCreateDialogProps) {
  const { t } = useI18n();

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t.knowledge.createSpace}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !name.trim(),
      })}
      onConfirm={onConfirm}
    >
      <SpaceFormFields
        name={name}
        setName={setName}
        description={description}
        setDescription={setDescription}
        access={access}
        setAccess={setAccess}
        ingestMode={ingestMode}
        setIngestMode={setIngestMode}
        topK={topK}
        setTopK={setTopK}
        score={score}
        setScore={setScore}
        disabled={busy}
        nameAutoFocus={open}
      />
    </FormDialog>
  );
}

interface SpaceEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  space: Space | null;
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  access: string;
  setAccess: (v: string) => void;
  ingestMode: UploadMode;
  setIngestMode: (v: UploadMode) => void;
  topK: string;
  setTopK: (v: string) => void;
  score: string;
  setScore: (v: string) => void;
  busy: boolean;
  deleteBusy?: boolean;
  onConfirm: () => void;
  onDelete: () => void | Promise<void>;
}

export function SpaceEditDialog({
  open,
  onOpenChange,
  space,
  name,
  setName,
  description,
  setDescription,
  access,
  setAccess,
  ingestMode,
  setIngestMode,
  topK,
  setTopK,
  score,
  setScore,
  busy,
  deleteBusy = false,
  onConfirm,
  onDelete,
}: SpaceEditDialogProps) {
  const { t, locale } = useI18n();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const editResourceMeta = buildSpaceEditMeta(space, locale, t.knowledge);
  const pending = busy || deleteBusy;

  return (
    <>
      <FormDialog
        open={open}
        onOpenChange={onOpenChange}
        title={t.knowledge.editSpace}
        editResourceMeta={editResourceMeta}
        {...dialogSaveFooterProps(t.common, {
          busy: pending,
          disabled: !name.trim(),
        })}
        onConfirm={onConfirm}
        leadingDestructive={{
          label: t.common.delete,
          onClick: () => setDeleteOpen(true),
          disabled: pending,
        }}
      >
        <SpaceFormFields
          name={name}
          setName={setName}
          description={description}
          setDescription={setDescription}
          access={access}
          setAccess={setAccess}
          ingestMode={ingestMode}
          setIngestMode={setIngestMode}
          topK={topK}
          setTopK={setTopK}
          score={score}
          setScore={setScore}
          disabled={pending}
          nameAutoFocus={open}
        />
      </FormDialog>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        description={t.common.deleteConfirm}
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
