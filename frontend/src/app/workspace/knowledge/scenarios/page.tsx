"use client";

import { ArrowLeftRightIcon, SettingsIcon, Trash2Icon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  AlertError,
  CardAction,
  ConfirmDialog,
  HeaderCreateButton,
  HeaderOutlineButton,
  InlineEmpty,
  ItemListPanel,
  ListPanelToolbar,
  ListSearchField,
  PanelEmpty,
  Shell,
  ShellHeader,
} from "@/components/component";
import { workspacePageInsetXClass } from "@/components/component/styles";
import {
  CatalogHostSwitchDialog,
  ScenarioCreateDialog,
  ScenarioEditDialog,
} from "@/components/workspace/knowledge/scenarios";
import { useI18n } from "@/core/i18n/hooks";
import {
  deleteScenario,
  listCatalog,
  listMySpaces,
  migrateCatalogHost,
  readStoredCatalogHost,
  scenarioLabel,
  scenarioMatchesCatalogHost,
  storeCatalogHost,
  upsertScenario,
  type KnowledgeCatalogResponse,
  type ScenarioPack,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

function ScenarioCatalogCard({
  scenario,
  onEdit,
  onDelete,
  deleteBusy,
}: {
  scenario: ScenarioPack;
  onEdit: (scenario: ScenarioPack) => void;
  onDelete: (scenario: ScenarioPack) => void;
  deleteBusy: boolean;
}) {
  const { t } = useI18n();
  const kb = t.knowledge;

  return (
    <li className="border-border/60 bg-card rounded-xl border px-4 py-3 shadow-none">
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="text-foreground shrink-0 text-sm font-medium">
              {scenarioLabel(scenario.type, kb, scenario)}
            </h3>
            <span className="text-muted-foreground shrink-0 font-mono text-xs">
              {scenario.type}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <CardAction
            icon={SettingsIcon}
            label={t.common.edit}
            onClick={() => onEdit(scenario)}
            disabled={deleteBusy}
          />
          <CardAction
            icon={Trash2Icon}
            label={t.common.delete}
            onClick={() => onDelete(scenario)}
            disabled={deleteBusy}
          />
        </div>
      </div>
    </li>
  );
}

export default function KnowledgeScenariosPage() {
  const { t, locale } = useI18n();
  const kb = t.knowledge;
  const router = useRouter();
  const searchParams = useSearchParams();
  const hostParam = searchParams.get("host")?.trim();
  const spaceParam = searchParams.get("space")?.trim();
  let queryHost: string | null = null;
  if (hostParam && hostParam.length > 0) queryHost = hostParam;
  else if (spaceParam && spaceParam.length > 0) queryHost = spaceParam;
  const [catalog, setCatalog] = useState<KnowledgeCatalogResponse | null>(null);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [editing, setEditing] = useState<ScenarioPack | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [scenarioToDelete, setScenarioToDelete] = useState<ScenarioPack | null>(
    null,
  );
  const [hostSwitchOpen, setHostSwitchOpen] = useState(false);
  const [hostSwitchBusy, setHostSwitchBusy] = useState(false);

  const catalogHostId = useMemo(() => {
    if (queryHost) return queryHost;
    return readStoredCatalogHost();
  }, [queryHost]);

  useEffect(() => {
    if (!queryHost) return;
    storeCatalogHost(queryHost);
  }, [queryHost]);

  const reload = useCallback(async () => {
    try {
      const [catalogRes, spacesRes] = await Promise.all([
        listCatalog(),
        listMySpaces(),
      ]);
      setCatalog(catalogRes);
      setSpaces(spacesRes.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, locale]);

  const scenarios = catalog?.scenarios ?? [];
  const hostScenarios = useMemo(
    () => scenarios.filter((s) => scenarioMatchesCatalogHost(s, catalogHostId)),
    [catalogHostId, scenarios],
  );

  const q = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!q) return hostScenarios;
    return hostScenarios.filter((s) => {
      const label = scenarioLabel(s.type, kb, s).toLowerCase();
      return (
        s.type.toLowerCase().includes(q) ||
        label.includes(q) ||
        (s.description?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [hostScenarios, kb, q]);

  const countLabel = useMemo(() => {
    if (scenarios.length === 0) return undefined;
    const total = hostScenarios.length;
    if (q) return kb.catalogCountFiltered(filtered.length, total);
    return kb.catalogCountTotal(total);
  }, [filtered.length, hostScenarios.length, kb, q, scenarios.length]);

  const isEmpty = scenarios.length === 0 && !error;
  const currentHostSpace = spaces.find((s) => s.id === catalogHostId);

  function navigateToHost(hostId: string) {
    storeCatalogHost(hostId);
    router.push(
      `/workspace/knowledge/scenarios?host=${encodeURIComponent(hostId)}`,
    );
  }

  async function onCreateScenario(input: { code: string; label: string }) {
    setCreateBusy(true);
    setError(null);
    try {
      await upsertScenario(input.code, {
        code: input.code,
        label: input.label,
        host_space_id: catalogHostId ?? undefined,
      });
      setCreateOpen(false);
      toast.success(kb.scenarioCreated);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreateBusy(false);
    }
  }

  async function onSaveScenario(input: { label: string }) {
    if (!editing) return;
    setEditBusy(true);
    setError(null);
    try {
      await upsertScenario(editing.type, {
        code: editing.type,
        label: input.label,
        description: editing.description,
        kinds: editing.kinds,
        lanes: editing.lanes,
      });
      setEditing(null);
      toast.success(kb.scenarioUpdated);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditBusy(false);
    }
  }

  async function removeScenario(target: ScenarioPack) {
    setDeleteBusy(true);
    setError(null);
    try {
      await deleteScenario(target.type);
      if (editing?.type === target.type) setEditing(null);
      setScenarioToDelete(null);
      toast.success(kb.scenarioDeleted);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setDeleteBusy(false);
    }
  }

  async function onDeleteFromEditDialog() {
    if (!editing) return;
    await removeScenario(editing);
  }

  async function onMigrateCatalogHost(hostSpaceId: string) {
    setHostSwitchBusy(true);
    setError(null);
    try {
      const res = await migrateCatalogHost(hostSpaceId);
      setHostSwitchOpen(false);
      toast.success(kb.catalogMigrated(res.updated));
      await reload();
      navigateToHost(res.host_space_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setHostSwitchBusy(false);
    }
  }

  const headerDescription =
    catalogHostId && currentHostSpace
      ? kb.catalogMigrateHostCurrent(
          currentHostSpace.name?.trim() || catalogHostId,
        )
      : kb.catalogDescription;

  return (
    <>
      <Shell
        fillBody={isEmpty}
        header={
          <ShellHeader
            backHref="/workspace/knowledge"
            title={kb.catalogTitle}
            description={headerDescription}
            actions={
              <>
                {spaces.length > 0 ? (
                  <HeaderOutlineButton
                    leading={<ArrowLeftRightIcon className="size-3.5" />}
                    onClick={() => setHostSwitchOpen(true)}
                  >
                    {kb.catalogSwitchSpace}
                  </HeaderOutlineButton>
                ) : null}
                <HeaderCreateButton onClick={() => setCreateOpen(true)}>
                  {kb.createScenario}
                </HeaderCreateButton>
              </>
            }
          />
        }
      >
        {error ? <AlertError>{error}</AlertError> : null}

        <ItemListPanel
          countLabel={countLabel}
          toolbar={
            scenarios.length > 0 ? (
              <ListPanelToolbar>
                <ListSearchField
                  value={query}
                  onChange={setQuery}
                  placeholder={kb.catalogSearchPlaceholder}
                />
              </ListPanelToolbar>
            ) : undefined
          }
        >
          {isEmpty ? (
            <PanelEmpty className="py-16">
              <p className="text-foreground font-medium">{kb.catalogEmpty}</p>
              <button
                type="button"
                className="text-primary mt-3 text-sm font-medium hover:underline"
                onClick={() => setCreateOpen(true)}
              >
                {kb.createScenario}
              </button>
            </PanelEmpty>
          ) : filtered.length === 0 ? (
            <InlineEmpty className="p-6">{kb.catalogSearchEmpty}</InlineEmpty>
          ) : (
            <div className={cn(workspacePageInsetXClass, "pt-2 pb-3")}>
              <ul className="flex flex-col gap-3">
                {filtered.map((scenario) => (
                  <ScenarioCatalogCard
                    key={scenario.type}
                    scenario={scenario}
                    onEdit={setEditing}
                    onDelete={setScenarioToDelete}
                    deleteBusy={deleteBusy}
                  />
                ))}
              </ul>
            </div>
          )}
        </ItemListPanel>
      </Shell>

      <ScenarioCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        busy={createBusy}
        onConfirm={onCreateScenario}
      />

      <ScenarioEditDialog
        open={editing != null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        scenario={editing}
        busy={editBusy}
        deleteBusy={deleteBusy}
        onConfirm={onSaveScenario}
        onDelete={onDeleteFromEditDialog}
      />

      <CatalogHostSwitchDialog
        open={hostSwitchOpen}
        onOpenChange={setHostSwitchOpen}
        spaces={spaces}
        currentHostId={catalogHostId}
        busy={hostSwitchBusy}
        onConfirm={onMigrateCatalogHost}
      />

      <ConfirmDialog
        open={scenarioToDelete != null}
        onOpenChange={(open) => {
          if (!open) setScenarioToDelete(null);
        }}
        title={t.common.delete}
        description={kb.catalogDeleteConfirm}
        confirmLabel={deleteBusy ? t.common.loading : t.common.delete}
        confirmPending={deleteBusy}
        confirmVariant="destructive"
        onConfirm={() => {
          if (scenarioToDelete) void removeScenario(scenarioToDelete);
        }}
        onCancel={() => setScenarioToDelete(null)}
      />
    </>
  );
}
