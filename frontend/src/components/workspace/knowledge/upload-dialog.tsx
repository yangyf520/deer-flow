"use client";

import { FileIcon, FileUpIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  UploadModeToggle,
  type UploadMode,
} from "@/app/workspace/knowledge/ui";
import {
  AlertError,
  DialogFieldGrid,
  DialogFormSection,
  DialogSlotField,
  DialogTextareaField,
  FormDialog,
  ItemList,
  ItemListPanel,
  ItemRow,
  dialogSaveFooterProps,
} from "@/components/component";
import {
  readOnlyFieldClass,
  workspaceFieldFocusClass,
} from "@/components/component/styles";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  defaultLegalSegmentPrompt,
  parseDocument,
  structuredMarkdownFile,
  type DocParseMeta,
  type ParsedDetail,
  type ParsedDocumentData,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

const PARSE_PREVIEW_PAGE_SIZE = 10;

export interface StructuredPreparedUpload {
  file: File;
  title?: string;
  segmentCount?: number;
}

export interface UploadInput {
  file: File;
  ingestMode: UploadMode;
  segmentPrompt?: string;
  prepared?: StructuredPreparedUpload;
}

interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultIngestMode: UploadMode;
  busy: boolean;
  onUpload: (input: UploadInput) => void | Promise<void>;
  onCancelUpload?: () => void;
}

type ParsePreviewState = {
  data: ParsedDocumentData;
  meta: DocParseMeta;
  prepared: StructuredPreparedUpload;
};

function segmentHeading(detail: ParsedDetail): string {
  return [detail.chapter_path, detail.segment_label]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(" · ");
}

export function UploadDialog({
  open,
  onOpenChange,
  defaultIngestMode,
  busy,
  onUpload,
  onCancelUpload,
}: UploadDialogProps) {
  const { t, locale } = useI18n();
  const fileRef = useRef<HTMLInputElement>(null);
  const parseAbortRef = useRef<AbortController | null>(null);
  const [ingestMode, setIngestMode] = useState<UploadMode>(defaultIngestMode);
  const [file, setFile] = useState<File | null>(null);
  const [segmentPrompt, setSegmentPrompt] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsePreview, setParsePreview] = useState<ParsePreviewState | null>(
    null,
  );
  const [previewVisibleCount, setPreviewVisibleCount] = useState(
    PARSE_PREVIEW_PAGE_SIZE,
  );

  useEffect(() => {
    if (!open) return;
    setIngestMode(defaultIngestMode);
    setFile(null);
    setSegmentPrompt(defaultLegalSegmentPrompt(locale));
    setParsing(false);
    setParseError(null);
    setParsePreview(null);
    setPreviewVisibleCount(PARSE_PREVIEW_PAGE_SIZE);
    parseAbortRef.current?.abort();
    parseAbortRef.current = null;
    if (fileRef.current) fileRef.current.value = "";
  }, [defaultIngestMode, locale, open]);

  const structured = ingestMode === "structured";
  const promptReady = !structured || segmentPrompt.trim().length > 0;
  const details = parsePreview?.data.details ?? [];
  const visibleDetails = details.slice(0, previewVisibleCount);
  const hasMorePreview = visibleDetails.length < details.length;

  const confirmLabel = structured
    ? parsePreview
      ? t.knowledge.vectorize
      : t.knowledge.parseAction
    : t.knowledge.upload;

  const confirmBusyLabel = structured
    ? parsePreview
      ? t.knowledge.vectorizing
      : t.knowledge.structuredParsing
    : t.knowledge.uploading;

  const confirmDisabled = structured
    ? parsePreview
      ? busy
      : !file || !promptReady || parsing
    : !file || busy;

  const confirmPending = structured ? parsing || busy : busy;

  function resetParsePreview() {
    setParsePreview(null);
    setParseError(null);
    setPreviewVisibleCount(PARSE_PREVIEW_PAGE_SIZE);
  }

  function openFilePicker() {
    if (busy || parsing) return;
    fileRef.current?.click();
  }

  function handleClose(openNext: boolean) {
    if (!openNext && (busy || parsing)) {
      parseAbortRef.current?.abort();
      onCancelUpload?.();
    }
    onOpenChange(openNext);
  }

  async function handleParse() {
    if (!file || !promptReady || parsing || busy) return;
    const controller = new AbortController();
    parseAbortRef.current?.abort();
    parseAbortRef.current = controller;
    setParsing(true);
    setParseError(null);
    resetParsePreview();
    try {
      const response = await parseDocument(file, segmentPrompt.trim(), {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      const { file: markdownFile, title } = structuredMarkdownFile(
        response.data,
        file.name,
      );
      setParsePreview({
        data: response.data,
        meta: response.meta,
        prepared: {
          file: markdownFile,
          title,
          segmentCount: response.data.details?.length ?? 0,
        },
      });
      setPreviewVisibleCount(PARSE_PREVIEW_PAGE_SIZE);
    } catch (e) {
      if (controller.signal.aborted) return;
      setParseError(e instanceof Error ? e.message : String(e));
    } finally {
      if (parseAbortRef.current === controller) {
        parseAbortRef.current = null;
      }
      setParsing(false);
    }
  }

  function handleConfirm() {
    if (!file || !promptReady) return;
    if (structured) {
      if (!parsePreview) {
        void handleParse();
        return;
      }
      void onUpload({
        file,
        ingestMode,
        segmentPrompt: segmentPrompt.trim(),
        prepared: parsePreview.prepared,
      });
      return;
    }
    void onUpload({ file, ingestMode });
  }

  const previewCountLabel = useMemo(() => {
    if (details.length === 0) return undefined;
    return `${visibleDetails.length}/${details.length}`;
  }, [details.length, visibleDetails.length]);

  return (
    <FormDialog
      open={open}
      onOpenChange={handleClose}
      title={
        <>
          {t.knowledge.uploadDialogTitle}
          <span className="text-muted-foreground ml-1.5 text-sm font-normal">
            {t.knowledge.uploadDialogDescription}
          </span>
        </>
      }
      {...dialogSaveFooterProps(t.common, {
        busy: confirmPending,
        disabled: confirmDisabled,
        busyLabel: confirmBusyLabel,
        saveLabel: confirmLabel,
      })}
      onCancel={() => {
        if (busy || parsing) {
          parseAbortRef.current?.abort();
          onCancelUpload?.();
        }
      }}
      onConfirm={handleConfirm}
    >
      <DialogFormSection contentClassName="gap-4">
        <DialogFieldGrid className="items-end">
          <DialogSlotField label={t.knowledge.uploadModeLabel}>
            <UploadModeToggle
              value={ingestMode}
              onValueChange={(mode) => {
                setIngestMode(mode);
                resetParsePreview();
              }}
              disabled={busy || parsing}
              className="w-full"
            />
          </DialogSlotField>

          <DialogSlotField label={t.knowledge.uploadFileLabel}>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              disabled={busy || parsing}
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                resetParsePreview();
              }}
            />
            <button
              type="button"
              disabled={busy || parsing}
              onClick={openFilePicker}
              className={cn(
                readOnlyFieldClass,
                workspaceFieldFocusClass,
                "hover:bg-muted/30 w-full justify-between gap-3 transition-colors",
                !busy && !parsing && "cursor-pointer",
              )}
            >
              <span className="flex min-w-0 flex-1 items-center gap-2">
                {file ? (
                  <FileIcon className="text-primary size-3.5 shrink-0" />
                ) : (
                  <FileUpIcon className="text-muted-foreground size-3.5 shrink-0" />
                )}
                <span
                  className={cn(
                    "truncate",
                    file ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  {file?.name ?? t.knowledge.noFileSelected}
                </span>
              </span>
              <span className="text-muted-foreground shrink-0 text-xs">
                {t.knowledge.selectFile}
              </span>
            </button>
          </DialogSlotField>
        </DialogFieldGrid>

        {structured ? (
          <DialogTextareaField
            label={t.knowledge.uploadSegmentPromptLabel}
            value={segmentPrompt}
            onChange={(value) => {
              setSegmentPrompt(value);
              resetParsePreview();
            }}
            disabled={busy || parsing}
            rows={6}
            autoGrow
            colSpan="full"
          />
        ) : null}

        {parseError ? <AlertError>{parseError}</AlertError> : null}

        {structured && parsePreview ? (
          <ItemListPanel
            title={t.knowledge.parsePreviewTitle}
            countLabel={previewCountLabel}
            className="max-h-72"
            footer={
              hasMorePreview ? (
                <div className="border-border/50 border-t px-4 py-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full"
                    disabled={busy || parsing}
                    onClick={() =>
                      setPreviewVisibleCount(
                        (count) => count + PARSE_PREVIEW_PAGE_SIZE,
                      )
                    }
                  >
                    {t.common.loadMore}
                  </Button>
                </div>
              ) : undefined
            }
          >
            <div className="max-h-56 min-h-0 overflow-y-auto">
              <ItemList variant="flush">
                {visibleDetails.map((detail, index) => {
                  const heading = segmentHeading(detail);
                  const body = detail.body?.trim();
                  return (
                    <ItemRow
                      key={`${heading}-${index}`}
                      variant="flush"
                      title={heading || `#${index + 1}`}
                      description={
                        body ? (
                          <span className="line-clamp-3 whitespace-pre-wrap">
                            {body}
                          </span>
                        ) : undefined
                      }
                    />
                  );
                })}
              </ItemList>
            </div>
          </ItemListPanel>
        ) : null}
      </DialogFormSection>
    </FormDialog>
  );
}
