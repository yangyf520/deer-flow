"use client";

import {
  AccessSelect,
  KindSelect,
  ScenarioSelect,
} from "@/app/workspace/knowledge/ui";
import {
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogSlotField,
  FormDialog,
  buildFormDialogEditResourceMeta,
  dialogSaveFooterProps,
} from "@/components/component";
import { readOnlyFieldClass } from "@/components/component/styles";
import { useI18n } from "@/core/i18n/hooks";
import type { ScenarioPack, Space } from "@/core/knowledge";
import { roleLabel } from "@/core/knowledge";
import { cn } from "@/lib/utils";

function ignoreAllowedKindChange(_value: string) {
  return;
}

function KnowledgeSpaceFormFields({
  name,
  setName,
  description,
  setDescription,
  access,
  setAccess,
  scenarioType,
  setScenarioType,
  scenarios,
  scenarioKindOptions,
  allowedKind,
  setAllowedKind,
  disabled,
  nameAutoFocus,
  showAllowedKinds,
}: {
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  access: string;
  setAccess: (v: string) => void;
  scenarioType: string;
  setScenarioType: (v: string) => void;
  scenarios: ScenarioPack[];
  scenarioKindOptions: Array<{ id: string }>;
  allowedKind: string;
  setAllowedKind: (v: string) => void;
  disabled?: boolean;
  nameAutoFocus?: boolean;
  showAllowedKinds?: boolean;
}) {
  const { t } = useI18n();

  return (
    <DialogFormSection>
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
        <DialogSlotField label={t.knowledge.fieldScenario}>
          <ScenarioSelect
            value={scenarioType || undefined}
            onValueChange={(value) => {
              setScenarioType(value);
              if (showAllowedKinds) {
                setAllowedKind("__all__");
              }
            }}
            scenarios={scenarios}
            disabled={Boolean(disabled) || scenarios.length === 0}
            className="w-full"
            placeholder={
              showAllowedKinds
                ? t.knowledge.selectScenario
                : t.knowledge.bindScenario
            }
          />
        </DialogSlotField>
        {showAllowedKinds && scenarioKindOptions.length > 0 ? (
          <DialogSlotField label={t.knowledge.fieldAllowedKinds} colSpan="full">
            <KindSelect
              value={allowedKind}
              onValueChange={setAllowedKind}
              kinds={scenarioKindOptions}
              allLabel={t.knowledge.allAllowedKinds}
              showId
              disabled={disabled}
              className="w-full"
              placeholder={t.knowledge.selectAllowedKinds}
            />
          </DialogSlotField>
        ) : null}
      </DialogFieldGrid>
    </DialogFormSection>
  );
}

interface KnowledgeSpaceCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  access: string;
  setAccess: (v: string) => void;
  scenarioType: string;
  setScenarioType: (v: string) => void;
  scenarios: ScenarioPack[];
  scenarioKindOptions: Array<{ id: string }>;
  allowedKind: string;
  setAllowedKind: (v: string) => void;
  busy: boolean;
  onConfirm: () => void;
}

export function KnowledgeSpaceCreateDialog({
  open,
  onOpenChange,
  name,
  setName,
  description,
  setDescription,
  access,
  setAccess,
  scenarioType,
  setScenarioType,
  scenarios,
  scenarioKindOptions,
  allowedKind,
  setAllowedKind,
  busy,
  onConfirm,
}: KnowledgeSpaceCreateDialogProps) {
  const { t } = useI18n();

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t.knowledge.createSpace}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !name.trim() || !scenarioType,
      })}
      onConfirm={onConfirm}
    >
      <KnowledgeSpaceFormFields
        name={name}
        setName={setName}
        description={description}
        setDescription={setDescription}
        access={access}
        setAccess={setAccess}
        scenarioType={scenarioType}
        setScenarioType={setScenarioType}
        scenarios={scenarios}
        scenarioKindOptions={scenarioKindOptions}
        allowedKind={allowedKind}
        setAllowedKind={setAllowedKind}
        disabled={busy}
        nameAutoFocus={open}
        showAllowedKinds
      />
    </FormDialog>
  );
}

interface KnowledgeSpaceEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  space: Space | null;
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  access: string;
  setAccess: (v: string) => void;
  scenarioType: string;
  setScenarioType: (v: string) => void;
  scenarios: ScenarioPack[];
  busy: boolean;
  onConfirm: () => void;
}

export function KnowledgeSpaceEditDialog({
  open,
  onOpenChange,
  space,
  name,
  setName,
  description,
  setDescription,
  access,
  setAccess,
  scenarioType,
  setScenarioType,
  scenarios,
  busy,
  onConfirm,
}: KnowledgeSpaceEditDialogProps) {
  const { t, locale } = useI18n();
  const editMeta = buildFormDialogEditResourceMeta(space, locale);

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t.knowledge.editSpace}
      {...dialogSaveFooterProps(t.common, { busy, disabled: !name.trim() })}
      onConfirm={onConfirm}
    >
      <KnowledgeSpaceFormFields
        name={name}
        setName={setName}
        description={description}
        setDescription={setDescription}
        access={access}
        setAccess={setAccess}
        scenarioType={scenarioType}
        setScenarioType={setScenarioType}
        scenarios={scenarios}
        scenarioKindOptions={[]}
        allowedKind="__all__"
        setAllowedKind={ignoreAllowedKindChange}
        disabled={busy}
        nameAutoFocus={open}
      />
      {space && (space.my_role || space.created_at) ? (
        <DialogFormSection title={t.common.resourceMeta.title}>
          <DialogFieldGrid>
            {space.my_role ? (
              <DialogSlotField label={t.knowledge.roleLabel}>
                <div className={readOnlyFieldClass}>
                  {roleLabel(space.my_role, t.knowledge)}
                </div>
              </DialogSlotField>
            ) : null}
            {space.created_at ? (
              <DialogSlotField label={t.common.resourceMeta.createdAt}>
                <div className={cn(readOnlyFieldClass, "tabular-nums")}>
                  {editMeta?.createdAt}
                </div>
              </DialogSlotField>
            ) : null}
          </DialogFieldGrid>
        </DialogFormSection>
      ) : null}
    </FormDialog>
  );
}
