"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
} from "@/components/component";
import { workspacePageInsetXClass } from "@/components/component/styles";
import {
  ApiKeyCard,
  ApiKeyCreateDialog,
  ApiKeyEditDialog,
  ApiKeyRevokeDialog,
  NO_AGENT,
  agentSelectValue,
} from "@/components/workspace/api-keys";
import {
  createApiKey,
  listAgentOptions,
  listApiKeys,
  revokeApiKey,
  updateApiKey,
  type AgentOption,
  type ApiKeySummary,
} from "@/core/api-keys";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export default function ApiKeysPage() {
  const { t } = useI18n();
  const ak = t.settings.apiKeys;
  const [keys, setKeys] = useState<ApiKeySummary[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
  const [deleting, setDeleting] = useState<ApiKeySummary | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
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
        (!key.agent_name && ak.unboundAgent.toLowerCase().includes(q)),
    );
  }, [ak.unboundAgent, keys, q]);

  const isListEmpty = !loading && keys.length === 0;

  const countLabel = useMemo(() => {
    if (loading || keys.length === 0) return undefined;
    if (q) return ak.countFiltered(filteredKeys.length, keys.length);
    return ak.countTotal(keys.length);
  }, [ak, filteredKeys.length, keys.length, loading, q]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [keyList, agentList] = await Promise.all([
        listApiKeys(),
        listAgentOptions(),
      ]);
      setKeys(keyList);
      setAgents(agentList);
      setError(null);
    } catch {
      setError(ak.loadError);
    } finally {
      setLoading(false);
    }
  }, [ak.loadError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function resetCreateForm() {
    setCreateName("");
    setCreateDescription("");
    setCreateAgent(NO_AGENT);
    setCreatedKey(null);
  }

  function onCloseCreate() {
    setCreateOpen(false);
    resetCreateForm();
  }

  async function onCreate() {
    if (!createName.trim()) {
      return;
    }
    setCreateBusy(true);
    setError(null);
    try {
      const created = await createApiKey({
        name: createName.trim(),
        description: createDescription.trim() || null,
        agent_name: createAgent === NO_AGENT ? null : createAgent,
      });
      setCreatedKey(created.key);
      setCreateName("");
      setCreateDescription("");
      setCreateAgent(NO_AGENT);
      toast.success(ak.createButton);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : ak.createError);
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
    if (!editing || !editName.trim()) {
      return;
    }
    setEditBusy(true);
    setError(null);
    try {
      await updateApiKey(editing.id, {
        name: editName.trim(),
        description: editDescription.trim() || null,
        agent_name: editAgent === NO_AGENT ? null : editAgent,
      });
      setEditing(null);
      toast.success(ak.updateSuccess);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : ak.updateError);
    } finally {
      setEditBusy(false);
    }
  }

  async function onConfirmDelete() {
    if (!deleting) {
      return;
    }
    setDeleteBusy(true);
    setError(null);
    try {
      await revokeApiKey(deleting.id);
      setDeleting(null);
      setEditing(null);
      toast.success(ak.revokeSuccess);
      await reload();
    } catch {
      setError(ak.revokeError);
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
        {error ? <AlertError>{error}</AlertError> : null}

        <ItemListPanel
          title={ak.listTitle}
          countLabel={countLabel}
          toolbar={
            !loading && !isListEmpty ? (
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
          {loading ? (
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
                  <ApiKeyCard key={key.id} apiKey={key} onEdit={openEdit} />
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
        createdKey={createdKey}
        onConfirm={() => void onCreate()}
        onClose={onCloseCreate}
      />

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
        deleteBusy={deleteBusy}
        onConfirm={() => void onSaveEdit()}
        onRevoke={() => editing && setDeleting(editing)}
      />

      <ApiKeyRevokeDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
        busy={deleteBusy}
        onConfirm={() => void onConfirmDelete()}
      />
    </>
  );
}
