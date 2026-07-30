"use client";

import {
  FileUpIcon,
  FlaskConicalIcon,
  RotateCcwIcon,
  SearchIcon,
  SettingsIcon,
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

import {
  KindSelect,
  ScenarioSelect,
  boundScenarioType,
} from "@/app/workspace/knowledge/ui";
import {
  AlertError,
  InlineEmpty,
  ItemListPanel,
  Shell,
  ShellHeader,
} from "@/components/component";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tooltip } from "@/components/workspace/tooltip";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import {
  deleteDocument,
  getSpace,
  importDocument,
  kindLabel,
  listDocumentChunks,
  listDocuments,
  listKinds,
  listScenarios,
  phaseLabel,
  reindexDocument,
  statusLabel,
  updateDocument,
  uploadKindsForSpace,
  defaultUploadKind,
  docKindOptionsFor,
  POLICY_TAG_GROUPS,
  tagGroupLabel,
  tagsFromPolicyGroups,
  policyGroupsFromTags,
  type PolicyTagGroupId,
  type DocumentChunk,
  type KnowledgeDocument,
  type KnowledgeKind,
  type ScenarioPack,
  type Space,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

type KnowledgeT = Translations["knowledge"];

function NoticeBanner({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <p className="bg-muted/50 text-muted-foreground rounded-lg border px-3 py-2 text-sm">
      {children}
    </p>
  );
}

const DOC_PAGE_SIZE = 20;

function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "ready") return "default";
  if (status === "failed") return "destructive";
  if (status === "processing") return "secondary";
  return "outline";
}

function ingestBadgeLabel(doc: KnowledgeDocument, t: KnowledgeT): string {
  if (doc.status === "ready") return t.status.ready;
  if (doc.status === "failed") return t.status.failed;
  if (doc.job_phase === "embedding") return t.phase.embedding;
  if (doc.job_phase === "parsing") return t.phase.parsing;
  if (doc.job_phase === "queued") return t.phase.queued;
  return statusLabel(doc.status, t);
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

function sameTitleAsFilename(doc: KnowledgeDocument): boolean {
  const title = doc.title.trim().toLowerCase();
  const name = doc.source_filename.trim().toLowerCase();
  if (!title || !name) return false;
  if (title === name) return true;
  const stem = name.replace(/\.[^.]+$/, "");
  return title === stem;
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
  const fileRef = useRef<HTMLInputElement>(null);
  const reindexFileRef = useRef<HTMLInputElement>(null);
  const [reindexTargetId, setReindexTargetId] = useState<string | null>(null);
  const [space, setSpace] = useState<Space | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioPack[]>([]);
  const [kinds, setKinds] = useState<KnowledgeKind[]>([]);
  /** List filter: ``__all__`` shows every kind; a concrete id also sets upload kind. */
  const [kindFilter, setKindFilter] = useState<string>("__all__");
  const [uploadKind, setUploadKind] = useState<string>("");
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [docsTotal, setDocsTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
  const [editDoc, setEditDoc] = useState<KnowledgeDocument | null>(null);
  const [editKind, setEditKind] = useState("");
  const [editTagGroups, setEditTagGroups] = useState<PolicyTagGroupId[]>([]);
  const [metaSaving, setMetaSaving] = useState(false);
  const [docsLoadingMore, setDocsLoadingMore] = useState(false);
  const [docToDelete, setDocToDelete] = useState<KnowledgeDocument | null>(
    null,
  );

  const uploadKindOptions = useMemo(
    () => uploadKindsForSpace(space, kinds, scenarios),
    [space, kinds, scenarios],
  );

  const effectiveUploadKind =
    kindFilter !== "__all__" ? kindFilter : uploadKind;

  const docListFilters = useMemo(
    () => ({
      kind: kindFilter === "__all__" ? undefined : kindFilter,
      q: deferredDocQuery || undefined,
    }),
    [deferredDocQuery, kindFilter],
  );

  const hasMoreDocs = docs.length < docsTotal;

  const reload = useCallback(async () => {
    try {
      const [s, d] = await Promise.all([
        getSpace(spaceId),
        listDocuments(
          spaceId,
          DOC_PAGE_SIZE,
          0,
          docListFilters.kind,
          docListFilters.q,
        ),
      ]);
      setSpace(s);
      setDocs(d.items);
      setDocsTotal(d.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [docListFilters, spaceId]);

  const loadMoreDocs = useCallback(async () => {
    if (!hasMoreDocs || docsLoadingMore) return;
    setDocsLoadingMore(true);
    try {
      const d = await listDocuments(
        spaceId,
        DOC_PAGE_SIZE,
        docs.length,
        docListFilters.kind,
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

  useEffect(() => {
    void listKinds()
      .then((res) => setKinds(res.items))
      .catch(() => setKinds([]));
  }, []);

  useEffect(() => {
    const next = defaultUploadKind(uploadKindOptions);
    setUploadKind((prev) =>
      prev && uploadKindOptions.some((k) => k.id === prev)
        ? prev
        : (next ?? ""),
    );
    setKindFilter((prev) =>
      prev === "__all__" || uploadKindOptions.some((k) => k.id === prev)
        ? prev
        : "__all__",
    );
  }, [uploadKindOptions]);

  function onKindFilterChange(value: string) {
    setKindFilter(value);
    if (value !== "__all__") setUploadKind(value);
  }

  useEffect(() => {
    void listScenarios()
      .then((res) => setScenarios(res.items))
      .catch(() => setScenarios([]));
  }, []);

  useEffect(() => {
    void reload();
    const timer = setInterval(() => void reload(), 3000);
    return () => clearInterval(timer);
  }, [reload]);

  async function onSaveDocMeta() {
    if (!editDoc) return;
    setMetaSaving(true);
    try {
      const tags =
        editKind === "policy"
          ? tagsFromPolicyGroups(editTagGroups)
          : (editDoc.tags ?? []);
      await updateDocument(spaceId, editDoc.id, {
        kind: editKind !== editDoc.kind ? editKind : undefined,
        tags: editKind === "policy" ? tags : undefined,
      });
      setEditDoc(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setMetaSaving(false);
    }
  }

  function openEditDoc(doc: KnowledgeDocument) {
    setEditDoc(doc);
    setEditKind(doc.kind);
    setEditTagGroups(policyGroupsFromTags(doc.tags));
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

  async function onUpload(file: File | null) {
    if (!file || !effectiveUploadKind) return;
    setBusy(true);
    setNotice(null);
    try {
      const imported = await importDocument(spaceId, file, {
        kind: effectiveUploadKind,
      });
      if (fileRef.current) fileRef.current.value = "";
      if (imported.deduped) {
        setNotice(imported.message ?? t.knowledge.dedupedNotice);
        setError(null);
        await reload();
        return;
      }
      await reload();
      const docId = imported.doc_id;
      const deadline = Date.now() + 120_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        const d = await listDocuments(
          spaceId,
          DOC_PAGE_SIZE,
          0,
          docListFilters.kind,
          docListFilters.q,
        );
        setDocs(d.items);
        setDocsTotal(d.total);
        const row = d.items.find((x) => x.id === docId);
        if (!row || row.status === "ready" || row.status === "failed") break;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onReindex(doc: KnowledgeDocument, file: File) {
    setReindexingId(doc.id);
    try {
      await reindexDocument(spaceId, doc.id, file);
      await reload();
      const deadline = Date.now() + 120_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        const d = await listDocuments(
          spaceId,
          DOC_PAGE_SIZE,
          0,
          docListFilters.kind,
          docListFilters.q,
        );
        setDocs(d.items);
        setDocsTotal(d.total);
        const row = d.items.find((x) => x.id === doc.id);
        if (!row || row.status === "ready" || row.status === "failed") break;
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

  const docsCountLabel =
    docListFilters.q || docs.length < docsTotal
      ? t.knowledge.docsCountFiltered
          .replace("{filtered}", String(docs.length))
          .replace("{total}", String(docsTotal))
      : t.knowledge.docsCount.replace("{count}", String(docsTotal));

  const headerActions = (
    <>
      <input
        ref={fileRef}
        type="file"
        className="hidden"
        disabled={busy}
        onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
      />
      <Button
        disabled={busy || !effectiveUploadKind}
        onClick={() => fileRef.current?.click()}
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
    </>
  );

  const docsToolbar = (
    <>
      <KindSelect
        value={kindFilter}
        onValueChange={onKindFilterChange}
        kinds={uploadKindOptions}
        allLabel={t.knowledge.filterAllKinds}
        className="h-8 w-full sm:w-44"
        placeholder={t.knowledge.selectKind}
      />
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
                scenarios={scenarios}
                placeholder={t.knowledge.bindScenario}
              />
            }
            actions={headerActions}
          />
        }
      >
        {error ? <AlertError>{error}</AlertError> : null}
        <NoticeBanner>{notice}</NoticeBanner>

        <ItemListPanel
          title={t.knowledge.docsList}
          countLabel={docsCountLabel}
          toolbar={docsToolbar}
          footer={
            hasMoreDocs ? (
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={docsLoadingMore || busy}
                onClick={() => void loadMoreDocs()}
              >
                {docsLoadingMore ? t.common.loading : t.common.loadMore}
              </Button>
            ) : undefined
          }
        >
          {docs.length === 0 ? (
            <InlineEmpty
              className="py-10"
              onClick={
                kindFilter === "__all__" &&
                !docListFilters.q &&
                !busy &&
                effectiveUploadKind
                  ? () => fileRef.current?.click()
                  : undefined
              }
            >
              {kindFilter !== "__all__" || docListFilters.q
                ? t.knowledge.noMatchingDocs
                : t.knowledge.emptyDocs}
            </InlineEmpty>
          ) : (
            <ul className="divide-border divide-y">
              {docs.map((d) => {
                const detail = ingestDetail(d, t.knowledge);
                const showFilename = !sameTitleAsFilename(d);
                const uploadedAt = formatUploadedAt(d.created_at, locale);
                const uploader = uploaderLabel(d, user);
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
                          <Badge
                            key="status"
                            variant={statusVariant(d.status)}
                            className="h-5 px-1.5 text-[10px] font-normal"
                          >
                            {ingestBadgeLabel(d, t.knowledge)}
                          </Badge>,
                          <Badge
                            key="kind"
                            variant="secondary"
                            className="h-5 px-1.5 text-[10px] font-normal"
                          >
                            {kindLabel(d.kind, t.knowledge)}
                          </Badge>,
                          ...policyGroupsFromTags(d.tags).map((groupId) => (
                            <Badge
                              key={`tag-group-${groupId}`}
                              variant="secondary"
                              className="h-5 px-1.5 text-[10px] font-normal"
                            >
                              {tagGroupLabel(groupId, t.knowledge)}
                            </Badge>
                          )),
                          showFilename ? (
                            <span key="file" className="truncate">
                              {d.source_filename}
                            </span>
                          ) : null,
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
                        {d.status === "ready" || d.status === "failed" ? (
                          <Tooltip content={t.common.edit}>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 px-2"
                              disabled={busy || metaSaving}
                              onClick={() => openEditDoc(d)}
                            >
                              <SettingsIcon className="size-3.5" />
                              {t.common.edit}
                            </Button>
                          </Tooltip>
                        ) : null}
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
                        <Tooltip content={t.knowledge.deleteTooltip}>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 px-2"
                            disabled={deletingId === d.id || busy}
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
        </ItemListPanel>
      </Shell>

      <Dialog
        open={editDoc != null}
        onOpenChange={(open) => {
          if (!open) setEditDoc(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.common.edit}</DialogTitle>
          </DialogHeader>
          {uploadKindOptions.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                {t.knowledge.fieldKind}
              </span>
              <p className="text-muted-foreground text-sm">
                {t.knowledge.fieldKindHint}
              </p>
              <Select
                value={editKind}
                disabled={metaSaving || !editDoc}
                onValueChange={setEditKind}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {editDoc
                    ? docKindOptionsFor(editDoc, uploadKindOptions).map((k) => (
                        <SelectItem key={k.id} value={k.id}>
                          {kindLabel(k.id, t.knowledge)}
                        </SelectItem>
                      ))
                    : null}
                </SelectContent>
              </Select>
            </div>
          ) : null}
          {editKind === "policy" ? (
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                {t.knowledge.editTags}
              </span>
              <p className="text-muted-foreground text-sm">
                {t.knowledge.uploadTagsHint}
              </p>
              <div className="flex flex-wrap gap-2 py-1">
                {POLICY_TAG_GROUPS.map((group) => {
                  const checked = editTagGroups.includes(group.id);
                  return (
                    <label
                      key={group.id}
                      className={cn(
                        "border-input bg-background flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1.5 text-sm",
                        checked && "border-primary bg-primary/5",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="size-3.5 accent-[var(--primary)]"
                        checked={checked}
                        disabled={metaSaving}
                        onChange={() => {
                          setEditTagGroups((prev) =>
                            checked
                              ? prev.filter((id) => id !== group.id)
                              : [...prev, group.id],
                          );
                        }}
                      />
                      <span>{tagGroupLabel(group.id, t.knowledge)}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={metaSaving}
              onClick={() => setEditDoc(null)}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              disabled={metaSaving}
              onClick={() => void onSaveDocMeta()}
            >
              {metaSaving ? t.common.loading : t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={docToDelete != null}
        onOpenChange={(open) => {
          if (!open) setDocToDelete(null);
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t.common.delete}</DialogTitle>
            <DialogDescription>{t.common.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={deletingId === docToDelete?.id}
              onClick={() => setDocToDelete(null)}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deletingId === docToDelete?.id}
              onClick={() => {
                if (docToDelete) void onDelete(docToDelete);
              }}
            >
              {deletingId === docToDelete?.id
                ? t.common.loading
                : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
    </>
  );
}
