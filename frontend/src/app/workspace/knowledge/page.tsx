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
  SpaceCard,
  SpaceCreateDialog,
  SpaceEditDialog,
} from "@/components/workspace/knowledge";
import { useI18n } from "@/core/i18n/hooks";
import {
  createSpace,
  deleteSpace,
  listMySpaces,
  spaceEditIdentifier,
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
  const [spaceId, setSpaceId] = useState("");
  const [description, setDescription] = useState("");
  const [access, setAccess] = useState("open");
  const [topK, setTopK] = useState(String(DEFAULT_TOP_K));
  const [score, setScore] = useState(String(DEFAULT_SCORE));
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingSpace, setEditingSpace] = useState<Space | null>(null);
  const [editSpaceId, setEditSpaceId] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editAccess, setEditAccess] = useState("open");
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
          s.id.toLowerCase().includes(q) ||
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
    const trimmedId = spaceId.trim();
    if (!trimmedId) return;
    setBusy(true);
    try {
      const retrieval = parseRetrievalPayload(topK, score);
      await createSpace({
        id: trimmedId,
        name: trimmedId,
        description: description.trim() || undefined,
        access,
        top_k: retrieval.top_k,
        score: retrieval.score,
      });
      setSpaceId("");
      setDescription("");
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
    setEditSpaceId(spaceEditIdentifier(space));
    setEditDescription(space.description ?? "");
    setEditAccess(space.access);
    setEditTopK(
      space.top_k != null ? String(space.top_k) : String(DEFAULT_TOP_K),
    );
    setEditScore(
      space.score != null ? String(space.score) : String(DEFAULT_SCORE),
    );
  }

  async function onSaveEditSpace() {
    if (!editingSpace) return;
    const trimmedId = editSpaceId.trim();
    if (!trimmedId) {
      setError(t.knowledge.fieldName);
      return;
    }
    setEditBusy(true);
    setError(null);
    try {
      const retrieval = parseRetrievalPayload(editTopK, editScore);
      const idChanged = trimmedId !== editingSpace.id;
      await updateSpace(editingSpace.id, {
        id: idChanged ? trimmedId : undefined,
        name: trimmedId,
        description: editDescription.trim(),
        access: editAccess,
        top_k: retrieval.top_k,
        score: retrieval.score,
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
        spaceId={spaceId}
        setSpaceId={setSpaceId}
        description={description}
        setDescription={setDescription}
        access={access}
        setAccess={setAccess}
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
        spaceId={editSpaceId}
        setSpaceId={setEditSpaceId}
        description={editDescription}
        setDescription={setEditDescription}
        access={editAccess}
        setAccess={setEditAccess}
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
