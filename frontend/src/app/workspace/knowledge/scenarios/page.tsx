"use client";

import { ArrowLeftRightIcon, SettingsIcon, Trash2Icon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  CodeTableSpaceSwitchDialog,
  ScenarioCreateDialog,
  ScenarioEditDialog,
} from "@/components/workspace/knowledge/scenarios";
import { useI18n } from "@/core/i18n/hooks";
import {
  deleteScenario,
  listCodeTable,
  listMySpaces,
  migrateCodeTableHost,
  readStoredCodeTableSpace,
  scenarioInHostSpace,
  scenarioLabel,
  scenarioUnassigned,
  spaceDisplayLabel,
  storeCodeTableSpace,
  upsertScenario,
  type KnowledgeCodeTable,
  type ScenarioPack,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

function ScenarioRow({
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
  const [codeTable, setCodeTable] = useState<KnowledgeCodeTable | null>(null);
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
  const [spaceSwitchOpen, setSpaceSwitchOpen] = useState(false);
  const [spaceSwitchBusy, setSpaceSwitchBusy] = useState(false);
  const [attachBusy, setAttachBusy] = useState(false);
  const attachAttemptRef = useRef<string | null>(null);

  const hostSpaceId = useMemo(() => {
    if (queryHost) return queryHost;
    return readStoredCodeTableSpace();
  }, [queryHost]);

  useEffect(() => {
    if (!queryHost) return;
    storeCodeTableSpace(queryHost);
  }, [queryHost]);

  const reload = useCallback(async () => {
    try {
      const [codeTableRes, spacesRes] = await Promise.all([
        listCodeTable(),
        listMySpaces(),
      ]);
      setCodeTable(codeTableRes);
      setSpaces(spacesRes.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, locale]);

  const scenarios = codeTable?.scenarios ?? [];
  const spaceScenarios = useMemo(
    () => scenarios.filter((s) => scenarioInHostSpace(s, hostSpaceId)),
    [hostSpaceId, scenarios],
  );

  const q = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!q) return spaceScenarios;
    return spaceScenarios.filter((s) => {
      const label = scenarioLabel(s.type, kb, s).toLowerCase();
      return (
        s.type.toLowerCase().includes(q) ||
        label.includes(q) ||
        (s.description?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [spaceScenarios, kb, q]);

  const countLabel = useMemo(() => {
    if (!hostSpaceId || spaceScenarios.length === 0) return undefined;
    const total = spaceScenarios.length;
    if (q) return kb.codeTableCountFiltered(filtered.length, total);
    return kb.codeTableCountTotal(total);
  }, [filtered.length, hostSpaceId, kb, q, spaceScenarios.length]);

  useEffect(() => {
    attachAttemptRef.current = null;
  }, [hostSpaceId]);

  useEffect(() => {
    if (!hostSpaceId || codeTable === null || attachBusy) return;
    if (attachAttemptRef.current === hostSpaceId) return;

    const hasAssignedHere = scenarios.some((s) =>
      scenarioInHostSpace(s, hostSpaceId),
    );
    const hasUnassigned = scenarios.some(scenarioUnassigned);
    if (hasAssignedHere || !hasUnassigned) return;

    attachAttemptRef.current = hostSpaceId;
    let cancelled = false;
    void (async () => {
      setAttachBusy(true);
      setError(null);
      try {
        await migrateCodeTableHost(hostSpaceId, { onlyUnassigned: true });
        if (!cancelled) await reload();
      } catch (e) {
        attachAttemptRef.current = null;
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setAttachBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attachBusy, codeTable, hostSpaceId, reload, scenarios]);

  const needsHost = !hostSpaceId && spaces.length > 0;
  const isEmpty =
    hostSpaceId != null && spaceScenarios.length === 0 && !error && !attachBusy;
  const currentHostSpace = spaces.find((s) => s.id === hostSpaceId);

  function navigateToHostSpace(spaceId: string) {
    storeCodeTableSpace(spaceId);
    router.push(
      `/workspace/knowledge/scenarios?host=${encodeURIComponent(spaceId)}`,
    );
  }

  async function onCreateScenario(input: { code: string; label: string }) {
    setCreateBusy(true);
    setError(null);
    try {
      await upsertScenario(input.code, {
        code: input.code,
        label: input.label,
        host_space_id: hostSpaceId ?? undefined,
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

  async function onMigrateCodeTableHost(targetSpaceId: string) {
    setSpaceSwitchBusy(true);
    setError(null);
    try {
      const res = await migrateCodeTableHost(targetSpaceId);
      setSpaceSwitchOpen(false);
      toast.success(kb.codeTableMigrated(res.updated));
      await reload();
      navigateToHostSpace(res.host_space_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSpaceSwitchBusy(false);
    }
  }

  const headerDescription =
    hostSpaceId && currentHostSpace
      ? kb.codeTableMigrateSpaceCurrent(
          currentHostSpace.name?.trim() || hostSpaceId,
        )
      : kb.codeTableDescription;

  return (
    <>
      <Shell
        fillBody={isEmpty || attachBusy}
        header={
          <ShellHeader
            backHref="/workspace/knowledge"
            title={kb.codeTableTitle}
            description={headerDescription}
            actions={
              <>
                {spaces.length > 0 ? (
                  <HeaderOutlineButton
                    leading={<ArrowLeftRightIcon className="size-3.5" />}
                    onClick={() => setSpaceSwitchOpen(true)}
                  >
                    {kb.codeTableSwitchSpace}
                  </HeaderOutlineButton>
                ) : null}
                <HeaderCreateButton
                  onClick={() => setCreateOpen(true)}
                  disabled={!hostSpaceId}
                >
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
            hostSpaceId && spaceScenarios.length > 0 ? (
              <ListPanelToolbar>
                <ListSearchField
                  value={query}
                  onChange={setQuery}
                  placeholder={kb.codeTableSearchPlaceholder}
                />
              </ListPanelToolbar>
            ) : undefined
          }
        >
          {needsHost ? (
            <PanelEmpty className="py-16">
              <p className="text-foreground font-medium">
                {kb.codeTablePickSpace}
              </p>
              <ul className="mt-4 flex flex-col gap-2">
                {spaces.map((space) => (
                  <li key={space.id}>
                    <button
                      type="button"
                      className="text-primary text-sm font-medium hover:underline"
                      onClick={() => navigateToHostSpace(space.id)}
                    >
                      {spaceDisplayLabel(space)}
                    </button>
                  </li>
                ))}
              </ul>
            </PanelEmpty>
          ) : attachBusy ? (
            <PanelEmpty className="py-16">{t.common.loading}</PanelEmpty>
          ) : isEmpty ? (
            <PanelEmpty className="py-16">
              <p className="text-foreground font-medium">{kb.codeTableEmpty}</p>
              <button
                type="button"
                className="text-primary mt-3 text-sm font-medium hover:underline"
                onClick={() => setCreateOpen(true)}
              >
                {kb.createScenario}
              </button>
            </PanelEmpty>
          ) : filtered.length === 0 ? (
            <InlineEmpty className="p-6">{kb.codeTableSearchEmpty}</InlineEmpty>
          ) : (
            <div className={cn(workspacePageInsetXClass, "pt-2 pb-3")}>
              <ul className="flex flex-col gap-3">
                {filtered.map((scenario) => (
                  <ScenarioRow
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

      <CodeTableSpaceSwitchDialog
        open={spaceSwitchOpen}
        onOpenChange={setSpaceSwitchOpen}
        spaces={spaces}
        currentHostSpaceId={hostSpaceId}
        busy={spaceSwitchBusy}
        onConfirm={onMigrateCodeTableHost}
      />

      <ConfirmDialog
        open={scenarioToDelete != null}
        onOpenChange={(open) => {
          if (!open) setScenarioToDelete(null);
        }}
        title={t.common.delete}
        description={kb.codeTableDeleteConfirm}
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
