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
  KnowledgeSpaceCard,
  KnowledgeSpaceCreateDialog,
  KnowledgeSpaceEditDialog,
} from "@/components/workspace/knowledge";
import { useI18n } from "@/core/i18n/hooks";
import {
  boundScenarioType,
  createSpace,
  kindsForScenario,
  listMySpaces,
  listScenarios,
  updateSpace,
  type ScenarioPack,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

export default function KnowledgeSpacesPage() {
  const { t } = useI18n();
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioPack[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [access, setAccess] = useState("open");
  const [scenarioType, setScenarioType] = useState("");
  /** ``__all__`` = all kinds configured on the scenario lanes. */
  const [allowedKind, setAllowedKind] = useState("__all__");
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingSpace, setEditingSpace] = useState<Space | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editAccess, setEditAccess] = useState("open");
  const [editScenario, setEditScenario] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [query, setQuery] = useState("");

  const selectedScenario =
    scenarios.find((s) => s.type === scenarioType) ?? null;
  const scenarioKindOptions = kindsForScenario(selectedScenario);
  const q = query.trim().toLowerCase();
  const filteredSpaces = !q
    ? spaces
    : spaces.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.description?.toLowerCase().includes(q) ?? false),
      );

  const isListEmpty = spaces.length === 0 && !error;

  const countLabel = useMemo(() => {
    if (spaces.length === 0) return undefined;
    if (q)
      return t.knowledge.countFiltered(filteredSpaces.length, spaces.length);
    return t.knowledge.countTotal(spaces.length);
  }, [filteredSpaces.length, q, spaces.length, t.knowledge]);

  const reload = useCallback(async () => {
    try {
      const [spacesRes, scenariosRes] = await Promise.all([
        listMySpaces(),
        listScenarios(),
      ]);
      setSpaces(spacesRes.items);
      setScenarios(scenariosRes.items);
      setScenarioType((prev) => {
        if (prev && scenariosRes.items.some((s) => s.type === prev))
          return prev;
        return scenariosRes.items[0]?.type ?? "";
      });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function onCreate() {
    if (!name.trim() || !scenarioType) return;
    setBusy(true);
    try {
      await createSpace({
        name: name.trim(),
        description: description.trim() || undefined,
        access,
        scenario: scenarioType,
        allowed_kinds: allowedKind === "__all__" ? undefined : [allowedKind],
      });
      setName("");
      setDescription("");
      setAllowedKind("__all__");
      setCreateOpen(false);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function openEditSpace(space: Space) {
    setEditingSpace(space);
    setEditName(space.name);
    setEditDescription(space.description ?? "");
    setEditAccess(space.access);
    setEditScenario(boundScenarioType(space) ?? "");
  }

  async function onSaveEditSpace() {
    if (!editingSpace) return;
    const trimmedName = editName.trim();
    if (!trimmedName) {
      setError(t.knowledge.fieldName);
      return;
    }
    setEditBusy(true);
    setError(null);
    try {
      await updateSpace(editingSpace.id, {
        name: trimmedName,
        description: editDescription.trim(),
        access: editAccess,
        scenario: editScenario || undefined,
      });
      setEditingSpace(null);
      toast.success(t.knowledge.spaceUpdated);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditBusy(false);
    }
  }

  return (
    <>
      <Shell
        fillBody={isListEmpty}
        header={
          <ShellHeader
            title={t.knowledge.title}
            description={t.knowledge.description}
            actions={
              <HeaderCreateButton onClick={() => setCreateOpen(true)}>
                {t.knowledge.createSpace}
              </HeaderCreateButton>
            }
          />
        }
      >
        {error ? <AlertError>{error}</AlertError> : null}

        <ItemListPanel
          title={t.knowledge.listTitle}
          countLabel={countLabel}
          toolbar={
            !isListEmpty ? (
              <ListPanelToolbar>
                <ListSearchField
                  value={query}
                  onChange={setQuery}
                  placeholder={t.knowledge.searchPlaceholder}
                />
              </ListPanelToolbar>
            ) : undefined
          }
        >
          {isListEmpty ? (
            <PanelEmpty className="py-16">
              <p className="text-foreground font-medium">
                {t.knowledge.emptyTitle}
              </p>
              <p className="mt-2">{t.knowledge.emptyDescription}</p>
            </PanelEmpty>
          ) : filteredSpaces.length === 0 ? (
            <ListEmpty size="compact" align="center">
              {t.knowledge.searchEmpty}
            </ListEmpty>
          ) : (
            <div className={cn(workspacePageInsetXClass, "pt-2 pb-3")}>
              <ItemGrid density="dense">
                {filteredSpaces.map((s) => (
                  <KnowledgeSpaceCard
                    key={s.id}
                    space={s}
                    onEdit={openEditSpace}
                  />
                ))}
              </ItemGrid>
            </div>
          )}
        </ItemListPanel>
      </Shell>

      <KnowledgeSpaceCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
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
        busy={busy}
        onConfirm={() => void onCreate()}
      />

      <KnowledgeSpaceEditDialog
        open={editingSpace !== null}
        onOpenChange={(open) => {
          if (!open) setEditingSpace(null);
        }}
        space={editingSpace}
        name={editName}
        setName={setEditName}
        description={editDescription}
        setDescription={setEditDescription}
        access={editAccess}
        setAccess={setEditAccess}
        scenarioType={editScenario}
        setScenarioType={setEditScenario}
        scenarios={scenarios}
        busy={editBusy}
        onConfirm={() => void onSaveEditSpace()}
      />
    </>
  );
}
