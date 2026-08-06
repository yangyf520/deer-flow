"use client";

import { CopyIcon } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { toast } from "sonner";

import {
  ConfirmDialog,
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogShell,
  DialogSlotField,
  FormActions,
  FormDialog,
  buildFormDialogEditResourceMeta,
  dialogSaveFooterProps,
} from "@/components/component";
import { dialogFieldControlClass } from "@/components/component/styles";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AgentOption, ApiKeySummary } from "@/core/api-keys";
import { useAuth } from "@/core/auth/AuthProvider";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export const NO_AGENT = "__none__";

export function agentSelectValue(agentName: string | null): string {
  return agentName ?? NO_AGENT;
}

function agentSelectTriggerLabel(
  value: string,
  agents: AgentOption[],
  labels: { noAgentBinding: string; leadAgent: string },
): string {
  if (value === NO_AGENT) {
    return labels.noAgentBinding;
  }
  if (value === "lead_agent") {
    return labels.leadAgent;
  }
  return agents.find((agent) => agent.name === value)?.name ?? value;
}

function ApiKeyFormBody({
  ak,
  name,
  setName,
  description,
  setDescription,
  agent,
  setAgent,
  agentItems,
  agentSelectLabels,
  agents,
  disabled,
  nameAutoFocus,
}: {
  ak: ReturnType<typeof useI18n>["t"]["settings"]["apiKeys"];
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  agent: string;
  setAgent: (v: string) => void;
  agentItems: ReactNode;
  agentSelectLabels: { noAgentBinding: string; leadAgent: string };
  agents: AgentOption[];
  disabled?: boolean;
  nameAutoFocus?: boolean;
}) {
  return (
    <DialogFormSection title={ak.sectionBasic}>
      <DialogFieldGrid>
        <DialogInputField
          label={ak.fieldName}
          value={name}
          onChange={setName}
          placeholder={ak.namePlaceholder}
          maxLength={128}
          disabled={disabled}
          autoFocus={nameAutoFocus}
        />
        <DialogSlotField label={ak.fieldAgent}>
          <Select value={agent} onValueChange={setAgent} disabled={disabled}>
            <SelectTrigger className={cn(dialogFieldControlClass, "w-full")}>
              <SelectValue placeholder={ak.agentPlaceholder}>
                {agentSelectTriggerLabel(agent, agents, agentSelectLabels)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="max-w-[min(100vw-2rem,28rem)]">
              {agentItems}
            </SelectContent>
          </Select>
        </DialogSlotField>
        <DialogInputField
          label={ak.fieldDescription}
          value={description}
          onChange={setDescription}
          placeholder={ak.descriptionPlaceholder}
          maxLength={512}
          colSpan="full"
          disabled={disabled}
        />
      </DialogFieldGrid>
    </DialogFormSection>
  );
}

function CreatedKeyBody({
  createdKey,
  copyLabel,
}: {
  createdKey: string;
  copyLabel: string;
}) {
  const { t } = useI18n();

  async function onCopy() {
    try {
      const didCopy = await writeTextToClipboard(createdKey);
      if (didCopy) {
        toast.success(t.clipboard.copiedToClipboard);
        return;
      }
      toast.error(t.clipboard.failedToCopyToClipboard);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  }

  return (
    <div className="border-border/70 flex w-full max-w-full items-center gap-2 rounded-lg border px-3 py-2.5">
      <code className="min-w-0 overflow-x-auto font-mono text-xs whitespace-nowrap">
        {createdKey}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="shrink-0"
        onClick={() => void onCopy()}
      >
        <CopyIcon className="size-3.5" />
        {copyLabel}
      </Button>
    </div>
  );
}

const apiKeyCreatedDialogContentClass =
  "!w-max max-w-[min(calc(100vw-2rem),42rem)] min-w-[min(100%,18rem)] flex flex-col gap-3 p-4 sm:p-5";

export function ApiKeyCreatedDialog({
  open,
  onOpenChange,
  createdKey,
  onClose,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  createdKey: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;

  return (
    <DialogShell
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          onClose();
        } else {
          onOpenChange(next);
        }
      }}
      title={ak.createdTitle}
      description={ak.createdHint}
      contentClassName={apiKeyCreatedDialogContentClass}
      bodyClassName="shrink-0 overflow-visible pt-0"
      footer={<FormActions confirmLabel={t.common.close} onConfirm={onClose} />}
    >
      <CreatedKeyBody createdKey={createdKey} copyLabel={ak.copyButton} />
    </DialogShell>
  );
}

export function useApiKeyAgentSelectItems(agents: AgentOption[]) {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;

  const agentItems = useMemo(
    () => (
      <>
        <SelectItem value={NO_AGENT}>{ak.noAgentBinding}</SelectItem>
        <SelectItem value="lead_agent">{ak.leadAgent}</SelectItem>
        {agents.map((agent) => (
          <SelectItem
            key={agent.name}
            value={agent.name}
            textValue={`${agent.name} ${agent.description ?? ""}`.trim()}
            className="items-start py-2"
          >
            <div className="flex min-w-0 flex-col gap-0.5 pr-6">
              <span className="truncate leading-none font-medium">
                {agent.name}
              </span>
              {agent.description ? (
                <span className="text-muted-foreground line-clamp-2 text-xs leading-snug font-normal">
                  {agent.description}
                </span>
              ) : null}
            </div>
          </SelectItem>
        ))}
      </>
    ),
    [agents, ak.leadAgent, ak.noAgentBinding],
  );

  const agentSelectLabels = useMemo(
    () => ({
      noAgentBinding: ak.noAgentBinding,
      leadAgent: ak.leadAgent,
    }),
    [ak.leadAgent, ak.noAgentBinding],
  );

  return { agentItems, agentSelectLabels };
}

interface ApiKeyCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agents: AgentOption[];
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  agent: string;
  setAgent: (v: string) => void;
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ApiKeyCreateDialog({
  open,
  onOpenChange,
  agents,
  name,
  setName,
  description,
  setDescription,
  agent,
  setAgent,
  busy,
  onConfirm,
  onClose,
}: ApiKeyCreateDialogProps) {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;
  const { agentItems, agentSelectLabels } = useApiKeyAgentSelectItems(agents);

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          onClose();
        } else {
          onOpenChange(next);
        }
      }}
      title={ak.createButton}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !name.trim(),
        busyLabel: ak.creating,
      })}
      onConfirm={onConfirm}
    >
      <ApiKeyFormBody
        ak={ak}
        name={name}
        setName={setName}
        description={description}
        setDescription={setDescription}
        agent={agent}
        setAgent={setAgent}
        agentItems={agentItems}
        agentSelectLabels={agentSelectLabels}
        agents={agents}
        disabled={busy}
        nameAutoFocus={open}
      />
    </FormDialog>
  );
}

interface ApiKeyEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  apiKey: ApiKeySummary | null;
  agents: AgentOption[];
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  agent: string;
  setAgent: (v: string) => void;
  busy: boolean;
  deleteBusy: boolean;
  onConfirm: () => void;
  onRevoke: () => void;
}

export function ApiKeyEditDialog({
  open,
  onOpenChange,
  apiKey,
  agents,
  name,
  setName,
  description,
  setDescription,
  agent,
  setAgent,
  busy,
  deleteBusy,
  onConfirm,
  onRevoke,
}: ApiKeyEditDialogProps) {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const ak = t.settings.apiKeys;
  const { agentItems, agentSelectLabels } = useApiKeyAgentSelectItems(agents);

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={ak.editTitle}
      editResourceMeta={buildFormDialogEditResourceMeta(
        apiKey
          ? {
              created_at: apiKey.created_at,
              created_by_name: apiKey.created_by_name,
            }
          : null,
        locale,
        user,
      )}
      {...dialogSaveFooterProps(t.common, {
        busy,
        disabled: !name.trim(),
        busyLabel: ak.updating,
        saveLabel: ak.saveButton,
      })}
      onConfirm={onConfirm}
      leadingDestructive={{
        label: ak.revokeButton,
        onClick: onRevoke,
        disabled: busy || deleteBusy,
      }}
    >
      <ApiKeyFormBody
        ak={ak}
        name={name}
        setName={setName}
        description={description}
        setDescription={setDescription}
        agent={agent}
        setAgent={setAgent}
        agentItems={agentItems}
        agentSelectLabels={agentSelectLabels}
        agents={agents}
        disabled={busy || deleteBusy}
        nameAutoFocus={open}
      />
    </FormDialog>
  );
}

interface ApiKeyRevokeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  onConfirm: () => void;
}

export function ApiKeyRevokeDialog({
  open,
  onOpenChange,
  busy,
  onConfirm,
}: ApiKeyRevokeDialogProps) {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={ak.deleteTitle}
      description={ak.deleteDescription}
      confirmLabel={busy ? ak.revoking : ak.revokeButton}
      confirmPending={busy}
      confirmVariant="destructive"
      onConfirm={onConfirm}
    />
  );
}
