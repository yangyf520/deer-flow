"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import {
  AlertError,
  HeaderCreateButton,
  ItemGrid,
  ItemListPanel,
  ListEmpty,
  ListPanelToolbar,
  ListSearchField,
  PanelEmpty,
  Shell,
  ShellHeader,
  formatApiKeyPrefixDisplay,
} from "@/components/component";
import { workspacePageInsetXClass } from "@/components/component/styles";
import {
  ApiKeyCard,
  ApiKeyCreateDialog,
  ApiKeyCreatedDialog,
  ApiKeyDeleteDialog,
  ApiKeyDisableDialog,
  ApiKeyEditDialog,
  NO_AGENT,
  agentSelectValue,
} from "@/components/workspace/api-keys";
import { useAgents } from "@/core/agents";
import {
  createApiKey,
  deleteApiKey,
  disableApiKey,
  enableApiKey,
  isApiKeyDisabled,
  rememberApiKeyMaskedDisplay,
  updateApiKey,
  useApiKeys,
  type AgentOption,
  type ApiKeySummary,
} from "@/core/api-keys";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export default function ApiKeysPage() {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;
  const queryClient = useQueryClient();
  const { keys, isLoading, error: loadError } = useApiKeys();
  const { agents: agentRecords } = useAgents();
  const agents = useMemo<AgentOption[]>(
    () =>
      agentRecords.map((agent) => ({
        name: agent.name,
        description: agent.description || undefined,
      })),
    [agentRecords],
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [createAgent, setCreateAgent] = useState(NO_AGENT);
  const [createBusy, setCreateBusy] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [editing, setEditing] = useState<ApiKeySummary | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editAgent, setEditAgent] = useState(NO_AGENT);
  const [editBusy, setEditBusy] = useState(false);
  const [disabling, setDisabling] = useState<ApiKeySummary | null>(null);
  const [disableBusy, setDisableBusy] = useState(false);
  const [deleting, setDeleting] = useState<ApiKeySummary | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [enableBusy, setEnableBusy] = useState(false);
  const [query, setQuery] = useState("");

  const q = query.trim().toLowerCase();
  const filteredKeys = useMemo(() => {
    if (!q) {
      return keys;
    }
    return keys.filter(
      (key) =>
        key.name.toLowerCase().includes(q) ||
        (key.description?.toLowerCase().includes(q) ?? false) ||
        (key.created_by_name?.toLowerCase().includes(q) ?? false) ||
        key.prefix.toLowerCase().includes(q) ||
        (key.agent_name?.toLowerCase().includes(q) ?? false) ||
        (!key.agent_name && ak.unboundAgent.toLowerCase().includes(q)) ||
        agents.some(
          (agent) =>
            agent.name === key.agent_name &&
            (agent.description?.toLowerCase().includes(q) ?? false),
        ),
    );
  }, [agents, ak.unboundAgent, keys, q]);

  const listError =
    loadError instanceof Error
      ? loadError.message
      : loadError
        ? ak.loadError
        : actionError;

  const isListEmpty = !isLoading && keys.length === 0;

  const countLabel = useMemo(() => {
    if (isLoading) return undefined;
    if (keys.length === 0) return undefined;
    if (q) return ak.countFiltered(filteredKeys.length, keys.length);
    return ak.countTotal(keys.length);
  }, [ak, filteredKeys.length, isLoading, keys.length, q]);

  async function invalidateKeys() {
    await queryClient.invalidateQueries({ queryKey: ["api-keys"] });
  }

  function resetCreateForm() {
    setCreateName("");
    setCreateDescription("");
    setCreateAgent(NO_AGENT);
  }

  function onCloseCreate() {
    setCreateOpen(false);
    resetCreateForm();
  }

  function onCloseCreated() {
    setCreatedKey(null);
  }

  async function onCreate() {
    if (!createName.trim()) {
      return;
    }
    setCreateBusy(true);
    setActionError(null);
    try {
      const created = await createApiKey({
        name: createName.trim(),
        description: createDescription.trim() || null,
        agent_name: createAgent === NO_AGENT ? null : createAgent,
      });
      setCreateOpen(false);
      resetCreateForm();
      setCreatedKey(created.key);
      rememberApiKeyMaskedDisplay(
        created.id,
        formatApiKeyPrefixDisplay(created.key),
      );
      await invalidateKeys();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : ak.createError);
    } finally {
      setCreateBusy(false);
    }
  }

  function openEdit(key: ApiKeySummary) {
    setEditing(key);
    setEditName(key.name);
    setEditDescription(key.description ?? "");
    setEditAgent(agentSelectValue(key.agent_name));
  }

  async function onSaveEdit() {
    if (!editing || !editName.trim() || isApiKeyDisabled(editing)) {
      return;
    }
    setEditBusy(true);
    setActionError(null);
    try {
      await updateApiKey(editing.id, {
        name: editName.trim(),
        description: editDescription.trim() || null,
        agent_name: editAgent === NO_AGENT ? null : editAgent,
      });
      setEditing(null);
      toast.success(ak.updateSuccess);
      await invalidateKeys();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : ak.updateError);
    } finally {
      setEditBusy(false);
    }
  }

  async function onConfirmDisable() {
    if (!disabling) {
      return;
    }
    setDisableBusy(true);
    setActionError(null);
    try {
      await disableApiKey(disabling.id);
      setDisabling(null);
      setEditing(null);
      toast.success(ak.disableSuccess);
      await invalidateKeys();
    } catch {
      setActionError(ak.disableError);
    } finally {
      setDisableBusy(false);
    }
  }

  async function onEnable() {
    if (!editing) {
      return;
    }
    setEnableBusy(true);
    setActionError(null);
    try {
      await enableApiKey(editing.id);
      setEditing(null);
      toast.success(ak.enableSuccess);
      await invalidateKeys();
    } catch {
      setActionError(ak.enableError);
    } finally {
      setEnableBusy(false);
    }
  }

  async function onConfirmDelete() {
    if (!deleting) {
      return;
    }
    setDeleteBusy(true);
    setActionError(null);
    try {
      await deleteApiKey(deleting.id);
      setDeleting(null);
      setEditing(null);
      toast.success(ak.deleteSuccess);
      await invalidateKeys();
    } catch {
      setActionError(ak.deleteError);
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <>
      <Shell
        fillBody={isListEmpty}
        header={
          <ShellHeader
            title={ak.title}
            description={ak.description}
            actions={
              <HeaderCreateButton onClick={() => setCreateOpen(true)}>
                {ak.createButton}
              </HeaderCreateButton>
            }
          />
        }
      >
        {listError ? <AlertError>{listError}</AlertError> : null}

        <ItemListPanel
          title={ak.listTitle}
          countLabel={countLabel}
          toolbar={
            !isListEmpty ? (
              <ListPanelToolbar>
                <ListSearchField
                  value={query}
                  onChange={setQuery}
                  placeholder={ak.searchPlaceholder}
                />
              </ListPanelToolbar>
            ) : undefined
          }
        >
          {isLoading ? (
            <PanelEmpty className="py-16">{t.common.loading}</PanelEmpty>
          ) : isListEmpty ? (
            <PanelEmpty className="py-16">
              <p className="text-foreground font-medium">{ak.emptyTitle}</p>
              <p className="mt-2">{ak.emptyDescription}</p>
            </PanelEmpty>
          ) : filteredKeys.length === 0 ? (
            <ListEmpty size="compact" align="center">
              {ak.searchEmpty}
            </ListEmpty>
          ) : (
            <div className={cn(workspacePageInsetXClass, "pt-2 pb-3")}>
              <ItemGrid density="dense">
                {filteredKeys.map((key) => (
                  <ApiKeyCard
                    key={key.id}
                    apiKey={key}
                    agents={agents}
                    onEdit={openEdit}
                  />
                ))}
              </ItemGrid>
            </div>
          )}
        </ItemListPanel>
      </Shell>

      <ApiKeyCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        agents={agents}
        name={createName}
        setName={setCreateName}
        description={createDescription}
        setDescription={setCreateDescription}
        agent={createAgent}
        setAgent={setCreateAgent}
        busy={createBusy}
        onConfirm={() => void onCreate()}
        onClose={onCloseCreate}
      />

      {createdKey ? (
        <ApiKeyCreatedDialog
          open
          onOpenChange={(open) => {
            if (!open) {
              onCloseCreated();
            }
          }}
          createdKey={createdKey}
          onClose={onCloseCreated}
        />
      ) : null}

      <ApiKeyEditDialog
        open={Boolean(editing)}
        onOpenChange={(open) => !open && setEditing(null)}
        apiKey={editing}
        agents={agents}
        name={editName}
        setName={setEditName}
        description={editDescription}
        setDescription={setEditDescription}
        agent={editAgent}
        setAgent={setEditAgent}
        busy={editBusy}
        disableBusy={disableBusy}
        enableBusy={enableBusy}
        deleteBusy={deleteBusy}
        onConfirm={() => void onSaveEdit()}
        onDisable={() => editing && setDisabling(editing)}
        onEnable={() => void onEnable()}
        onDelete={() => editing && setDeleting(editing)}
      />

      <ApiKeyDisableDialog
        open={Boolean(disabling)}
        onOpenChange={(open) => !open && setDisabling(null)}
        busy={disableBusy}
        onConfirm={() => void onConfirmDisable()}
      />

      <ApiKeyDeleteDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
        busy={deleteBusy}
        onConfirm={() => void onConfirmDelete()}
      />
    </>
  );
}
