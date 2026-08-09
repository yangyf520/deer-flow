"use client";

import {
  FileUpIcon,
  FlaskConicalIcon,
  PencilIcon,
  RotateCcwIcon,
  SearchIcon,
  TablePropertiesIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import {
  ScenarioSelect,
  boundScenarioType,
  type UploadMode,
} from "@/app/workspace/knowledge/ui";
import {
  AlertError,
  ConfirmDialog,
  DateInput,
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogSlotField,
  DialogToggleField,
  FormDialog,
  InlineEmpty,
  ItemListInfiniteTail,
  ItemListPanel,
  ItemRowStatusBadge,
  Shell,
  ShellHeader,
  TimeInput,
  dateInputLang,
  dialogSaveFooterProps,
  itemRowStatusToneFromValue,
  joinLocalDateTime,
  splitLocalDateTime,
  type ItemRowStatusTone,
  useItemListInfiniteScroll,
} from "@/components/component";
import { workspacePageInsetXClass } from "@/components/component/styles";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  UploadDialog,
  type UploadInput,
} from "@/components/workspace/knowledge";
import { Tooltip } from "@/components/workspace/tooltip";
import { useAuth } from "@/core/auth/AuthProvider";
import { loadKnowledgeCodeTable } from "@/core/code-table/api";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import {
  deleteAllDocuments,
  deleteDocument,
  docIngestModeLabel,
  documentEffectiveStatus,
  type DocumentEffectiveStatus,
  effectiveToLocalValue,
  getSpace,
  importDocument,
  listDocumentChunks,
  listDocuments,
  localValueToEffectiveTo,
  parseDocument,
  readDocumentEnabled,
  resolveSegmentPrompt,
  structuredMarkdownFile,
  phaseLabel,
  readDocIngestMode,
  readStoredIngestMode,
  reindexDocument,
  statusLabel,
  storeDocIngestMode,
  storeIngestMode,
  tagGroupLabel,
  tagGroupsFromTags,
  updateDocument,
  importKindForSpace,
  scenarioInHostSpace,
  type DocumentChunk,
  type KnowledgeDocument,
  type KnowledgeTagGroup,
  type ScenarioPack,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

type KnowledgeT = Translations["knowledge"];

const DOC_PAGE_SIZE = 20;
const INGEST_POLL_MS = 3000;

function ingestBadgeLabel(doc: KnowledgeDocument, t: KnowledgeT): string {
  if (doc.status === "ready") {
    return readDocumentEnabled(doc.attrs)
      ? t.fieldDocumentAvailableYes
      : t.fieldDocumentAvailableNo;
  }
  if (doc.status === "failed") return t.status.failed;
  if (doc.job_phase === "embedding") return t.phase.embedding;
  if (doc.job_phase === "parsing") return t.phase.parsing;
  if (doc.job_phase === "queued") return t.phase.queued;
  return statusLabel(doc.status, t);
}

function ingestBadgeTone(doc: KnowledgeDocument) {
  if (doc.status === "ready") {
    return readDocumentEnabled(doc.attrs) ? "success" : "warning";
  }
  return itemRowStatusToneFromValue(doc.status);
}

function documentEffectiveBadgeLabel(
  status: DocumentEffectiveStatus,
  t: KnowledgeT,
): string {
  if (status === "expired") return t.documentEffectiveExpired;
  if (status === "pending") return t.documentEffectivePending;
  return t.documentEffectiveValid;
}

function documentEffectiveBadgeTone(
  status: DocumentEffectiveStatus,
): ItemRowStatusTone {
  if (status === "expired") return "danger";
  if (status === "pending") return "warning";
  return "success";
}

function ingestDetail(doc: KnowledgeDocument, t: KnowledgeT): string | null {
  if (doc.status === "ready") return null;
  if (doc.status === "failed") {
    return doc.error_message?.trim() ?? t.status.failed;
  }
  const pct = Number.isFinite(doc.progress) ? `${doc.progress}%` : "";
  return [phaseLabel(doc.job_phase || "queued", t), pct]
    .filter(Boolean)
    .join(" ");
}

function formatUploadedAt(
  iso: string | null | undefined,
  locale: string,
): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function displayNameFromEmail(email: string | null | undefined): string | null {
  const raw = email?.trim();
  if (!raw) return null;
  const local = raw.split("@")[0]?.trim() ?? "";
  return local !== "" ? local : raw;
}

function uploaderLabel(
  doc: KnowledgeDocument,
  currentUser: { id: string; email: string } | null,
): string | null {
  const named = doc.created_by_name?.trim();
  if (named) return named;
  if (currentUser && (!doc.created_by || doc.created_by === currentUser.id)) {
    return displayNameFromEmail(currentUser.email);
  }
  return null;
}

export default function KnowledgeSpaceDocumentsPage() {
  const params = useParams<{ spaceId: string }>();
  const spaceId = params.spaceId;
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const reindexFileRef = useRef<HTMLInputElement>(null);
  const [reindexTargetId, setReindexTargetId] = useState<string | null>(null);
  const [space, setSpace] = useState<Space | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioPack[]>([]);
  const spaceScenarios = useMemo(
    () =>
      scenarios.filter((scenario) => scenarioInHostSpace(scenario, spaceId)),
    [scenarios, spaceId],
  );
  const [tagGroups, setTagGroups] = useState<KnowledgeTagGroup[]>([]);
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [docsTotal, setDocsTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [reindexingId, setReindexingId] = useState<string | null>(null);
  const [docQuery, setDocQuery] = useState("");
  const deferredDocQuery = useDeferredValue(docQuery.trim().toLowerCase());
  const [chunkDoc, setChunkDoc] = useState<KnowledgeDocument | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [chunksTotal, setChunksTotal] = useState(0);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksError, setChunksError] = useState<string | null>(null);
  const [chunkQuery, setChunkQuery] = useState("");
  const deferredChunkQuery = useDeferredValue(chunkQuery.trim().toLowerCase());
  const filteredChunks = !deferredChunkQuery
    ? chunks
    : chunks.filter((c) => {
        const hay = [
          c.text,
          c.block,
          c.heading_path,
          c.index != null ? String(c.index) : "",
        ]
          .filter(Boolean)
          .join("\n")
          .toLowerCase();
        return hay.includes(deferredChunkQuery);
      });
  const [uploadOpen, setUploadOpen] = useState(false);
  const [ingestMode, setIngestMode] = useState<UploadMode>("unstructured");
  const [docsLoadingMore, setDocsLoadingMore] = useState(false);
  const [docToDelete, setDocToDelete] = useState<KnowledgeDocument | null>(
    null,
  );
  const [docToEdit, setDocToEdit] = useState<KnowledgeDocument | null>(null);
  const [editDocTitle, setEditDocTitle] = useState("");
  const [editDocAvailable, setEditDocAvailable] = useState(true);
  const [editDocExpiresAt, setEditDocExpiresAt] = useState("");
  const [editDocBusy, setEditDocBusy] = useState(false);
  const editExpiresParts = useMemo(
    () => splitLocalDateTime(editDocExpiresAt),
    [editDocExpiresAt],
  );
  const [deleteAllOpen, setDeleteAllOpen] = useState(false);
  const [deleteAllBusy, setDeleteAllBusy] = useState(false);
  const uploadAbortRef = useRef<AbortController | null>(null);

  const docListFilters = useMemo(
    () => ({
      q: deferredDocQuery || undefined,
    }),
    [deferredDocQuery],
  );

  const hasMoreDocs = docs.length < docsTotal;

  const hasProcessingDocs = useMemo(
    () => docs.some((d) => d.status === "processing"),
    [docs],
  );

  const loadSpace = useCallback(async () => {
    try {
      const s = await getSpace(spaceId);
      setSpace(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [spaceId]);

  const refreshDocuments = useCallback(async (): Promise<
    KnowledgeDocument[]
  > => {
    try {
      const d = await listDocuments(
        spaceId,
        DOC_PAGE_SIZE,
        0,
        undefined,
        docListFilters.q,
      );
      setDocs(d.items);
      setDocsTotal(d.total);
      setError(null);
      return d.items;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return [];
    }
  }, [docListFilters.q, spaceId]);

  const reload = useCallback(async () => {
    await Promise.all([loadSpace(), refreshDocuments()]);
  }, [loadSpace, refreshDocuments]);

  const loadMoreDocs = useCallback(async () => {
    if (!hasMoreDocs || docsLoadingMore) return;
    setDocsLoadingMore(true);
    try {
      const d = await listDocuments(
        spaceId,
        DOC_PAGE_SIZE,
        docs.length,
        undefined,
        docListFilters.q,
      );
      setDocs((prev) => [...prev, ...d.items]);
      setDocsTotal(d.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDocsLoadingMore(false);
    }
  }, [docListFilters, docs.length, docsLoadingMore, hasMoreDocs, spaceId]);

  const docsSentinelRef = useItemListInfiniteScroll({
    hasNextPage: hasMoreDocs,
    isFetchingNextPage: docsLoadingMore,
    onLoadMore: loadMoreDocs,
    listLength: docs.length,
  });

  useEffect(() => {
    setIngestMode(readStoredIngestMode(spaceId));
  }, [spaceId]);

  useEffect(() => {
    void loadKnowledgeCodeTable()
      .then((res) => {
        setScenarios(res.scenarios);
        setTagGroups(res.tag_groups);
      })
      .catch(() => {
        setScenarios([]);
        setTagGroups([]);
      });
  }, []);

  useEffect(() => {
    void loadSpace();
  }, [loadSpace]);

  useEffect(() => {
    void refreshDocuments();
  }, [refreshDocuments]);

  useEffect(() => {
    if (busy || !hasProcessingDocs) return;
    const timer = setInterval(() => void refreshDocuments(), INGEST_POLL_MS);
    return () => clearInterval(timer);
  }, [busy, hasProcessingDocs, refreshDocuments]);

  async function waitForDocumentIngest(docId: string, signal?: AbortSignal) {
    const deadline = Date.now() + 120_000;
    while (Date.now() < deadline) {
      if (signal?.aborted) return;
      const items = await refreshDocuments();
      const row = items.find((x) => x.id === docId);
      if (!row || row.status === "ready" || row.status === "failed") return;
      await new Promise((r) => setTimeout(r, INGEST_POLL_MS));
    }
  }

  function cancelUpload() {
    uploadAbortRef.current?.abort();
    uploadAbortRef.current = null;
    setBusy(false);
  }

  async function saveDocIngestMode(docId: string, mode: UploadMode) {
    storeDocIngestMode(docId, mode);
    await updateDocument(spaceId, docId, { attrs: { ingest_mode: mode } });
  }

  async function importUploadedFile(
    file: File,
    kind: string,
    ingestMode: UploadMode,
    title?: string,
    signal?: AbortSignal,
  ) {
    const embedded = await importDocument(
      spaceId,
      file,
      { kind, title, attrs: { ingest_mode: ingestMode } },
      { signal },
    );
    if (embedded.doc_id) {
      storeDocIngestMode(embedded.doc_id, ingestMode);
    }
    if (embedded.deduped) {
      if (embedded.doc_id) {
        await saveDocIngestMode(embedded.doc_id, ingestMode);
      }
      toast.success(embedded.message ?? t.knowledge.dedupedNotice);
      setError(null);
      await refreshDocuments();
      return embedded.doc_id;
    }
    await refreshDocuments();
    await waitForDocumentIngest(embedded.doc_id, signal);
    return embedded.doc_id;
  }

  async function onOpenChunks(doc: KnowledgeDocument) {
    setChunkDoc(doc);
    setChunks([]);
    setChunksTotal(0);
    setChunksError(null);
    setChunkQuery("");
    setChunksLoading(true);
    try {
      const res = await listDocumentChunks(spaceId, doc.id);
      setChunks(res.items);
      setChunksTotal(res.total);
    } catch (e) {
      setChunksError(e instanceof Error ? e.message : String(e));
    } finally {
      setChunksLoading(false);
    }
  }

  async function fileForIngest(
    file: File,
    mode: UploadMode,
    signal?: AbortSignal,
    segmentPrompt?: string,
  ): Promise<{ file: File; title?: string; segmentCount?: number }> {
    if (mode !== "structured") {
      return { file };
    }
    const prompt = resolveSegmentPrompt(segmentPrompt, locale);
    const parsed = await parseDocument(file, prompt, { signal });
    const { file: markdownFile, title } = structuredMarkdownFile(
      parsed.data,
      file.name,
    );
    return {
      file: markdownFile,
      title,
      segmentCount: parsed.data.details?.length ?? 0,
    };
  }

  async function onUploadFromDialog({
    file,
    ingestMode: mode,
    prepared,
  }: UploadInput) {
    if (!file) return;
    const kind = importKindForSpace(space);
    const controller = new AbortController();
    uploadAbortRef.current = controller;
    const { signal } = controller;
    setBusy(true);
    try {
      storeIngestMode(spaceId, mode);
      setIngestMode(mode);
      let importFile = file;
      let importTitle: string | undefined;
      let segmentCount: number | undefined;
      if (mode === "structured") {
        if (!prepared) return;
        importFile = prepared.file;
        importTitle = prepared.title;
        segmentCount = prepared.segmentCount;
      }
      const docId = await importUploadedFile(
        importFile,
        kind,
        mode,
        importTitle,
        signal,
      );
      if (signal.aborted) return;
      if (docId && mode === "structured") {
        toast.success(t.knowledge.structuredImported(segmentCount ?? 0));
      }
      setUploadOpen(false);
    } catch (e) {
      if (signal.aborted) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (uploadAbortRef.current === controller) {
        uploadAbortRef.current = null;
      }
      setBusy(false);
    }
  }

  async function onReindex(doc: KnowledgeDocument, file: File) {
    setReindexingId(doc.id);
    try {
      const prepared = await fileForIngest(file, ingestMode);
      await saveDocIngestMode(doc.id, ingestMode);
      await reindexDocument(spaceId, doc.id, prepared.file);
      await waitForDocumentIngest(doc.id);
      if (ingestMode === "structured") {
        toast.success(t.knowledge.structuredReindexed);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReindexingId(null);
      setReindexTargetId(null);
      if (reindexFileRef.current) reindexFileRef.current.value = "";
    }
  }

  function requestReindex(doc: KnowledgeDocument) {
    setReindexTargetId(doc.id);
    reindexFileRef.current?.click();
  }

  function openEditDocument(doc: KnowledgeDocument) {
    setDocToEdit(doc);
    setEditDocTitle(doc.title);
    setEditDocAvailable(readDocumentEnabled(doc.attrs));
    setEditDocExpiresAt(effectiveToLocalValue(doc.effective_to));
  }

  async function onSaveDocument() {
    if (!docToEdit) return;
    const trimmed = editDocTitle.trim();
    if (!trimmed) return;
    setEditDocBusy(true);
    try {
      const attrs = { ...(docToEdit.attrs ?? {}), enabled: editDocAvailable };
      const updated = await updateDocument(spaceId, docToEdit.id, {
        title: trimmed,
        effective_to: localValueToEffectiveTo(editDocExpiresAt),
        attrs,
      });
      setDocs((prev) =>
        prev.map((row) => (row.id === updated.id ? updated : row)),
      );
      setChunkDoc((current) =>
        current?.id === updated.id ? updated : current,
      );
      setDocToEdit(null);
      toast.success(t.knowledge.documentUpdated);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditDocBusy(false);
    }
  }

  async function onDelete(doc: KnowledgeDocument) {
    setDeletingId(doc.id);
    try {
      await deleteDocument(spaceId, doc.id);
      setDocToDelete(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeletingId(null);
    }
  }

  async function onDeleteAll() {
    setDeleteAllBusy(true);
    setError(null);
    try {
      await deleteAllDocuments(spaceId);
      setDeleteAllOpen(false);
      toast.success(t.knowledge.deleteAllSuccess);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleteAllBusy(false);
    }
  }

  const docsCountLabel =
    docListFilters.q || docs.length < docsTotal
      ? t.knowledge.docsCountFiltered
          .replace("{filtered}", String(docs.length))
          .replace("{total}", String(docsTotal))
      : t.knowledge.docsCount.replace("{count}", String(docsTotal));

  const headerActions = (
    <>
      <Button
        disabled={busy || !space}
        onClick={() => setUploadOpen(true)}
        variant="outline"
        size="sm"
        className="h-8 w-24 shrink-0 justify-center px-0"
      >
        <FileUpIcon className="size-3.5" />
        {busy ? t.knowledge.uploading : t.knowledge.upload}
      </Button>
      <Button
        asChild
        variant="outline"
        size="sm"
        className="h-8 w-24 shrink-0 justify-center px-0"
      >
        <Link href={`/workspace/knowledge/${spaceId}/eval`}>
          <FlaskConicalIcon className="size-3.5" />
          {t.knowledge.eval}
        </Link>
      </Button>
      <Button
        asChild
        variant="outline"
        size="sm"
        className="h-8 w-24 shrink-0 justify-center px-0"
      >
        <Link href="/workspace/code-table/knowledge">
          <TablePropertiesIcon className="size-3.5" />
          {t.knowledge.codeTableButton}
        </Link>
      </Button>
    </>
  );

  const docsToolbar = (
    <>
      <div className="relative min-w-0 flex-1 sm:w-56 sm:flex-none">
        <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
        <Input
          className={cn(
            "bg-background h-8 pl-8",
            docQuery ? "pr-8" : undefined,
          )}
          placeholder={t.knowledge.searchFilename}
          value={docQuery}
          onChange={(e) => setDocQuery(e.target.value)}
        />
        {docQuery ? (
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1.5 flex size-5 -translate-y-1/2 items-center justify-center rounded-sm"
            aria-label={t.common.clear}
            onClick={() => setDocQuery("")}
          >
            <XIcon className="size-3.5" />
          </button>
        ) : null}
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="text-destructive hover:text-destructive shrink-0"
        disabled={
          docsTotal === 0 ||
          busy ||
          deleteAllBusy ||
          deletingId != null ||
          reindexingId != null
        }
        onClick={() => setDeleteAllOpen(true)}
      >
        <Trash2Icon className="size-3.5" />
        {t.knowledge.deleteAllButton}
      </Button>
      <input
        ref={reindexFileRef}
        type="file"
        className="hidden"
        disabled={busy || reindexingId != null}
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          const target = docs.find((d) => d.id === reindexTargetId);
          if (file && target) void onReindex(target, file);
          else {
            setReindexTargetId(null);
            if (reindexFileRef.current) reindexFileRef.current.value = "";
          }
        }}
      />
    </>
  );

  return (
    <>
      <Shell
        fillBody={docs.length === 0}
        header={
          <ShellHeader
            backHref="/workspace/knowledge"
            title={space?.name ?? spaceId}
            description={space?.description ?? t.knowledge.docsSubtitle}
            descriptionSuffix={
              <ScenarioSelect
                readOnly
                value={boundScenarioType(space) ?? undefined}
                scenarios={spaceScenarios}
                placeholder={t.knowledge.bindScenario}
              />
            }
            actions={headerActions}
          />
        }
      >
        {error ? <AlertError>{error}</AlertError> : null}

        <ItemListPanel
          title={t.knowledge.docsList}
          countLabel={docsCountLabel}
          toolbar={docsToolbar}
        >
          {docs.length === 0 ? (
            <div className={cn(workspacePageInsetXClass, "py-2 sm:py-2.5")}>
              <InlineEmpty
                className="py-10"
                onClick={
                  !docListFilters.q && !busy && space
                    ? () => setUploadOpen(true)
                    : undefined
                }
              >
                {docListFilters.q
                  ? t.knowledge.noMatchingDocs
                  : t.knowledge.emptyDocs}
              </InlineEmpty>
            </div>
          ) : (
            <ul className="divide-border divide-y">
              {docs.map((d) => {
                const detail = ingestDetail(d, t.knowledge);
                const ingestModeLabel = docIngestModeLabel(
                  d,
                  t.knowledge,
                  readDocIngestMode(d.id),
                );
                const uploadedAt = formatUploadedAt(d.created_at, locale);
                const uploader = uploaderLabel(d, user);
                const effectiveStatus =
                  d.status === "ready" ? documentEffectiveStatus(d) : null;
                return (
                  <li
                    key={d.id}
                    className="hover:bg-muted/40 flex flex-col gap-1 px-4 py-2 transition-colors"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-3">
                      <button
                        type="button"
                        className="min-w-0 truncate text-left font-medium hover:underline"
                        onClick={() => void onOpenChunks(d)}
                        title={t.knowledge.viewChunks}
                      >
                        {d.title}
                      </button>
                      <div className="text-muted-foreground flex shrink-0 items-center gap-x-1.5 text-xs">
                        {uploader ? <span>{uploader}</span> : null}
                        {uploader && uploadedAt ? (
                          <span className="text-border">·</span>
                        ) : null}
                        {uploadedAt ? (
                          <span title={d.created_at ?? undefined}>
                            {uploadedAt}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center justify-between gap-2">
                      <div className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                        {[
                          <ItemRowStatusBadge
                            key="status"
                            tone={ingestBadgeTone(d)}
                          >
                            {ingestBadgeLabel(d, t.knowledge)}
                          </ItemRowStatusBadge>,
                          effectiveStatus ? (
                            <ItemRowStatusBadge
                              key="effective"
                              tone={documentEffectiveBadgeTone(effectiveStatus)}
                            >
                              {documentEffectiveBadgeLabel(
                                effectiveStatus,
                                t.knowledge,
                              )}
                            </ItemRowStatusBadge>
                          ) : null,
                          ingestModeLabel ? (
                            <Badge
                              key="ingest-mode"
                              variant="outline"
                              className="h-5 px-1.5 text-[10px] font-normal"
                            >
                              {ingestModeLabel}
                            </Badge>
                          ) : null,
                          ...tagGroupsFromTags(d.tags, tagGroups).map(
                            (groupId) => (
                              <Badge
                                key={`tag-group-${groupId}`}
                                variant="secondary"
                                className="h-5 px-1.5 text-[10px] font-normal"
                              >
                                {tagGroupLabel(groupId, t.knowledge)}
                              </Badge>
                            ),
                          ),
                          detail ? (
                            <span
                              key="detail"
                              className={cn(
                                d.status === "failed" && "text-destructive",
                              )}
                            >
                              {detail}
                            </span>
                          ) : null,
                        ]
                          .filter(Boolean)
                          .flatMap((node, i, arr) =>
                            i < arr.length - 1
                              ? [
                                  node,
                                  <span
                                    key={`sep-${i}`}
                                    className="text-border"
                                  >
                                    ·
                                  </span>,
                                ]
                              : [node],
                          )}
                      </div>
                      <div className="flex shrink-0 items-center gap-0.5">
                        {d.status === "failed" || d.status === "ready" ? (
                          <Tooltip content={t.knowledge.reindexTooltip}>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 px-2"
                              disabled={reindexingId === d.id || busy}
                              onClick={() => requestReindex(d)}
                            >
                              <RotateCcwIcon className="size-3.5" />
                              {reindexingId === d.id
                                ? t.knowledge.reindexing
                                : t.knowledge.reindex}
                            </Button>
                          </Tooltip>
                        ) : null}
                        <Tooltip content={t.knowledge.editDocument}>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 px-2"
                            disabled={editDocBusy && docToEdit?.id === d.id}
                            onClick={() => openEditDocument(d)}
                          >
                            <PencilIcon className="size-3.5" />
                            {t.common.edit}
                          </Button>
                        </Tooltip>
                        <Tooltip
                          content={
                            d.status === "processing"
                              ? t.knowledge.stopProcessingTooltip
                              : t.knowledge.deleteTooltip
                          }
                        >
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 px-2"
                            disabled={deletingId === d.id}
                            onClick={() => setDocToDelete(d)}
                          >
                            <Trash2Icon className="size-3.5" />
                            {deletingId === d.id
                              ? t.knowledge.deleting
                              : t.common.delete}
                          </Button>
                        </Tooltip>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {docs.length > 0 && hasMoreDocs ? (
            <ItemListInfiniteTail
              sentinelRef={docsSentinelRef}
              isFetchingNextPage={docsLoadingMore}
              loadingLabel={t.common.loading}
            />
          ) : null}
        </ItemListPanel>
      </Shell>

      <ConfirmDialog
        open={deleteAllOpen}
        onOpenChange={(open) => !open && setDeleteAllOpen(false)}
        title={t.knowledge.deleteAllTitle}
        description={t.knowledge.deleteAllDescription(docsTotal)}
        confirmLabel={
          deleteAllBusy ? t.knowledge.deleting : t.knowledge.deleteAllButton
        }
        confirmPending={deleteAllBusy}
        confirmVariant="destructive"
        onConfirm={() => void onDeleteAll()}
        onCancel={() => setDeleteAllOpen(false)}
      />

      <FormDialog
        open={docToEdit != null}
        onOpenChange={(open) => {
          if (!open && !editDocBusy) setDocToEdit(null);
        }}
        title={t.knowledge.editDocument}
        {...dialogSaveFooterProps(t.common, {
          busy: editDocBusy,
          disabled: !editDocTitle.trim(),
        })}
        onConfirm={() => void onSaveDocument()}
      >
        <DialogFormSection title={t.knowledge.sectionDocument}>
          <DialogInputField
            label={t.knowledge.fieldTitle}
            value={editDocTitle}
            onChange={setEditDocTitle}
            disabled={editDocBusy}
            autoFocus={docToEdit != null}
          />
        </DialogFormSection>

        <DialogFormSection title={t.knowledge.sectionDocumentAvailability}>
          <DialogFieldGrid>
            <DialogToggleField
              label={t.knowledge.fieldDocumentAvailable}
              value={editDocAvailable ? "yes" : "no"}
              onValueChange={(value) => setEditDocAvailable(value === "yes")}
              disabled={editDocBusy}
              items={[
                { value: "yes", label: t.knowledge.fieldDocumentAvailableYes },
                { value: "no", label: t.knowledge.fieldDocumentAvailableNo },
              ]}
            />
            <DialogSlotField
              label={t.knowledge.fieldDocumentExpiresAt}
              labelTrailing={
                <span className="text-muted-foreground truncate text-xs">
                  {t.knowledge.fieldDocumentExpiresAtHint}
                </span>
              }
            >
              <div className="flex min-w-0 gap-2" lang={dateInputLang(locale)}>
                <DateInput
                  value={editExpiresParts.date}
                  onChange={(nextDate) =>
                    setEditDocExpiresAt(
                      joinLocalDateTime(nextDate, editExpiresParts.time),
                    )
                  }
                  disabled={editDocBusy}
                  locale={locale}
                  aria-label={t.knowledge.fieldDocumentExpiresAtDate}
                  className="min-w-0 flex-1"
                />
                <TimeInput
                  value={editExpiresParts.time}
                  onChange={(nextTime) =>
                    setEditDocExpiresAt(
                      joinLocalDateTime(editExpiresParts.date, nextTime),
                    )
                  }
                  disabled={editDocBusy}
                  locale={locale}
                  aria-label={t.knowledge.fieldDocumentExpiresAtTime}
                  className="w-[7.5rem] shrink-0"
                />
              </div>
            </DialogSlotField>
          </DialogFieldGrid>
        </DialogFormSection>
      </FormDialog>

      <ConfirmDialog
        open={docToDelete != null}
        onOpenChange={(open) => {
          if (!open) setDocToDelete(null);
        }}
        title={t.common.delete}
        description={t.common.deleteConfirm}
        confirmLabel={
          deletingId === docToDelete?.id ? t.common.loading : t.common.delete
        }
        confirmPending={deletingId === docToDelete?.id}
        confirmVariant="destructive"
        onConfirm={() => {
          if (docToDelete) void onDelete(docToDelete);
        }}
        onCancel={() => setDocToDelete(null)}
      />

      <Sheet
        open={chunkDoc != null}
        onOpenChange={(open) => {
          if (!open) {
            setChunkDoc(null);
            setChunkQuery("");
          }
        }}
      >
        <SheetContent
          side="right"
          className="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-lg"
        >
          <SheetHeader className="shrink-0 border-b px-4 pb-3">
            <SheetTitle className="pr-8">
              {chunkDoc?.title ?? t.knowledge.chunks}
            </SheetTitle>
            <SheetDescription asChild>
              <div className="space-y-2">
                <p className="text-muted-foreground text-sm">
                  {chunkDoc?.source_filename
                    ? `${chunkDoc.source_filename} · `
                    : null}
                  {t.knowledge.chunksSummary.replace(
                    "{count}",
                    chunksLoading ? "…" : String(chunksTotal),
                  )}
                </p>
                <div className="relative">
                  <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
                  <Input
                    className={cn("h-8 pl-8", chunkQuery ? "pr-8" : undefined)}
                    placeholder={t.knowledge.searchChunks}
                    value={chunkQuery}
                    onChange={(e) => setChunkQuery(e.target.value)}
                    aria-label={t.common.search}
                  />
                  {chunkQuery ? (
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1.5 flex size-5 -translate-y-1/2 items-center justify-center rounded-sm"
                      aria-label={t.common.clear}
                      onClick={() => setChunkQuery("")}
                    >
                      <XIcon className="size-3.5" />
                    </button>
                  ) : null}
                </div>
              </div>
            </SheetDescription>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pt-3 pb-4">
            {chunksLoading ? (
              <p className="text-muted-foreground text-sm">
                {t.knowledge.chunksLoading}
              </p>
            ) : chunksError ? (
              <p className="text-destructive text-sm">{chunksError}</p>
            ) : chunks.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {chunkDoc?.status === "processing"
                  ? t.knowledge.chunksLoading
                  : chunkDoc?.status === "failed"
                    ? (chunkDoc.error_message?.trim() ??
                      t.knowledge.chunksEmpty)
                    : t.knowledge.chunksEmpty}
              </p>
            ) : filteredChunks.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {t.knowledge.searchChunksEmpty}
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {filteredChunks.map((c) => (
                  <li
                    key={c.id}
                    className="bg-muted/30 rounded-lg border px-3 py-2.5"
                  >
                    <div className="text-muted-foreground mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]">
                      <span className="font-mono tabular-nums">#{c.index}</span>
                      {c.block ? <span>{c.block}</span> : null}
                      <span className="tabular-nums">
                        {t.knowledge.charCount.replace(
                          "{count}",
                          String(c.char_count),
                        )}
                      </span>
                      {c.page != null ? <span>p.{c.page}</span> : null}
                      {c.heading_path ? (
                        <span className="truncate">{c.heading_path}</span>
                      ) : null}
                    </div>
                    <pre className="font-sans text-xs leading-relaxed break-words whitespace-pre-wrap">
                      {c.text || t.knowledge.emptyText}
                    </pre>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </SheetContent>
      </Sheet>

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        defaultIngestMode={ingestMode}
        busy={busy}
        onUpload={onUploadFromDialog}
        onCancelUpload={cancelUpload}
      />
    </>
  );
}
