"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import type { UploadMode } from "@/app/workspace/knowledge/ui";
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
  SpaceCard,
  SpaceCreateDialog,
  SpaceEditDialog,
} from "@/components/workspace/knowledge";
import { useI18n } from "@/core/i18n/hooks";
import {
  createSpace,
  deleteSpace,
  listMySpaces,
  readStoredIngestMode,
  storeIngestMode,
  updateSpace,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

const DEFAULT_TOP_K = 8;
const DEFAULT_SCORE = 0.35;

function parseRetrievalPayload(topK: string, score: string) {
  const parsedTopK = Number.parseInt(topK, 10);
  const parsedScore = Number.parseFloat(score);
  return {
    top_k:
      Number.isFinite(parsedTopK) && parsedTopK >= 1 && parsedTopK <= 50
        ? parsedTopK
        : DEFAULT_TOP_K,
    score:
      Number.isFinite(parsedScore) && parsedScore >= 0 && parsedScore <= 1
        ? parsedScore
        : DEFAULT_SCORE,
  };
}

export default function KnowledgeSpacesPage() {
  const { t } = useI18n();
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [access, setAccess] = useState("open");
  const [ingestMode, setIngestMode] = useState<UploadMode>("unstructured");
  const [topK, setTopK] = useState(String(DEFAULT_TOP_K));
  const [score, setScore] = useState(String(DEFAULT_SCORE));
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingSpace, setEditingSpace] = useState<Space | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editAccess, setEditAccess] = useState("open");
  const [editIngestMode, setEditIngestMode] =
    useState<UploadMode>("unstructured");
  const [editTopK, setEditTopK] = useState(String(DEFAULT_TOP_K));
  const [editScore, setEditScore] = useState(String(DEFAULT_SCORE));
  const [editBusy, setEditBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [query, setQuery] = useState("");

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
      const spacesRes = await listMySpaces();
      setSpaces(spacesRes.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function onCreate() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const retrieval = parseRetrievalPayload(topK, score);
      const created = await createSpace({
        name: name.trim(),
        description: description.trim() || undefined,
        access,
        top_k: retrieval.top_k,
        score: retrieval.score,
      });
      storeIngestMode(created.id, ingestMode);
      setName("");
      setDescription("");
      setIngestMode("unstructured");
      setTopK(String(DEFAULT_TOP_K));
      setScore(String(DEFAULT_SCORE));
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
    setEditIngestMode(readStoredIngestMode(space.id));
    setEditTopK(
      space.top_k != null ? String(space.top_k) : String(DEFAULT_TOP_K),
    );
    setEditScore(
      space.score != null ? String(space.score) : String(DEFAULT_SCORE),
    );
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
      const retrieval = parseRetrievalPayload(editTopK, editScore);
      await updateSpace(editingSpace.id, {
        name: trimmedName,
        description: editDescription.trim(),
        access: editAccess,
        top_k: retrieval.top_k,
        score: retrieval.score,
      });
      storeIngestMode(editingSpace.id, editIngestMode);
      setEditingSpace(null);
      toast.success(t.knowledge.spaceUpdated);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditBusy(false);
    }
  }

  async function onDeleteEditSpace() {
    if (!editingSpace) return;
    setDeleteBusy(true);
    setError(null);
    try {
      await deleteSpace(editingSpace.id);
      setEditingSpace(null);
      toast.success(t.common.delete);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
                  <SpaceCard key={s.id} space={s} onEdit={openEditSpace} />
                ))}
              </ItemGrid>
            </div>
          )}
        </ItemListPanel>
      </Shell>

      <SpaceCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
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
        busy={busy}
        onConfirm={() => void onCreate()}
      />

      <SpaceEditDialog
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
        ingestMode={editIngestMode}
        setIngestMode={setEditIngestMode}
        topK={editTopK}
        setTopK={setEditTopK}
        score={editScore}
        setScore={setEditScore}
        busy={editBusy}
        deleteBusy={deleteBusy}
        onConfirm={() => void onSaveEditSpace()}
        onDelete={() => onDeleteEditSpace()}
      />
    </>
  );
}
