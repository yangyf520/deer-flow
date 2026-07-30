"use client";

import {
  ChevronDownIcon,
  ChevronUpIcon,
  PlusIcon,
  PlayIcon,
  Trash2Icon,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { PageShell } from "@/app/workspace/knowledge/ui";
import { AlertError, Header, InlineEmpty } from "@/components/component";
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
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { searchKnowledge, type EvidenceItem } from "@/core/knowledge";

const DEFAULT_QUESTIONS = [""];
const PREVIEW_COUNT = 5;
const SNIPPET_PREVIEW_CHARS = 360;
const LOW_SCORE = 0.45;

type KnowledgeT = Translations["knowledge"];

type QuestionResult = {
  q: string;
  items: EvidenceItem[];
  latencyMs: number;
  traceId?: string | null;
};

function metaStr(
  meta: Record<string, unknown> | undefined,
  key: string,
): string | null {
  const v = meta?.[key];
  if (v == null || v === "") return null;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

function sourceLine(item: EvidenceItem, t: KnowledgeT): string {
  const parts: string[] = [];
  const docTitle = metaStr(item.metadata, "doc_title") ?? item.title;
  if (docTitle) parts.push(docTitle);
  const filename = metaStr(item.metadata, "source_filename");
  if (filename && filename !== docTitle) parts.push(filename);
  const heading = metaStr(item.metadata, "heading_path");
  if (heading && heading !== docTitle) parts.push(heading);
  const page = metaStr(item.metadata, "page_no");
  if (page) parts.push(`p.${page}`);
  return (
    (parts.length > 0 ? parts.join(" · ") : null) ??
    item.citable_as ??
    t.unknownSource
  );
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function HitCard({
  item,
  rank,
  t,
}: {
  item: EvidenceItem;
  rank: number;
  t: KnowledgeT;
}) {
  const [expanded, setExpanded] = useState(false);
  const block = metaStr(item.metadata, "block") ?? "text";
  const docId = metaStr(item.metadata, "doc_id");
  const heading = metaStr(item.metadata, "heading_path");
  const snippet = item.snippet?.trim() || t.emptySnippet;
  const long = snippet.length > SNIPPET_PREVIEW_CHARS;
  const shown =
    !long || expanded ? snippet : `${snippet.slice(0, SNIPPET_PREVIEW_CHARS)}…`;
  const score = item.score ?? null;
  const low = score != null && score < LOW_SCORE;

  return (
    <li className="bg-card rounded-xl border p-4 shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground text-xs font-medium">
              #{rank}
            </span>
            <Badge variant={block === "table" ? "default" : "secondary"}>
              {block}
            </Badge>
            {low ? <Badge variant="destructive">{t.lowScore}</Badge> : null}
          </div>
          <div className="mt-2 text-sm font-medium">
            {t.source.replace("{source}", sourceLine(item, t))}
          </div>
          {heading && item.title && heading !== item.title ? (
            <div className="text-muted-foreground mt-0.5 text-xs">
              {t.section.replace("{section}", heading)}
            </div>
          ) : null}
          {docId ? (
            <div className="text-muted-foreground mt-0.5 font-mono text-[11px]">
              doc {docId}
            </div>
          ) : null}
        </div>
        <Badge variant={low ? "destructive" : "secondary"} className="shrink-0">
          score {score?.toFixed?.(3) ?? score ?? "—"}
        </Badge>
      </div>

      <div className="bg-muted/50 mt-3 rounded-lg px-3 py-3">
        <div className="text-muted-foreground mb-1.5 text-[11px] font-medium tracking-wide">
          {t.matchedContent}
        </div>
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{shown}</p>
        {long ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-2 h-7 px-2 text-xs"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? (
              <>
                <ChevronUpIcon className="size-3.5" />
                {t.collapseFull}
              </>
            ) : (
              <>
                <ChevronDownIcon className="size-3.5" />
                {t.expandFull}
              </>
            )}
          </Button>
        ) : null}
      </div>

      {item.citable_as ? (
        <div className="text-muted-foreground mt-2 text-xs">
          {t.citable.replace("{cite}", item.citable_as)}
        </div>
      ) : null}
    </li>
  );
}

function QuestionBlock({
  result,
  index,
  t,
}: {
  result: QuestionResult;
  index: number;
  t: KnowledgeT;
}) {
  const [showAll, setShowAll] = useState(false);
  const topScore = result.items[0]?.score;
  const second = result.items[1]?.score;
  const gap =
    topScore != null && second != null
      ? Math.max(0, Number(topScore) - Number(second))
      : null;
  const uniqueDocs = new Set(
    result.items
      .map((i) => metaStr(i.metadata, "doc_id"))
      .filter(Boolean) as string[],
  ).size;
  const visible = showAll ? result.items : result.items.slice(0, PREVIEW_COUNT);
  const hidden = Math.max(0, result.items.length - PREVIEW_COUNT);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b pb-2">
        <h2 className="text-base font-medium">
          <span className="text-muted-foreground mr-2">Q{index + 1}</span>
          {result.q}
        </h2>
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span>{formatMs(result.latencyMs)}</span>
          <span>
            {result.items.length === 0
              ? t.noHits
              : t.hitsSummary
                  .replace("{count}", String(result.items.length))
                  .replace("{score}", topScore?.toFixed?.(3) ?? "—")}
          </span>
          {uniqueDocs > 0 ? (
            <span>{t.docsInvolved.replace("{count}", String(uniqueDocs))}</span>
          ) : null}
          {gap != null ? (
            <span>{t.scoreGap.replace("{gap}", gap.toFixed(3))}</span>
          ) : null}
        </div>
      </div>

      {result.items.length === 0 ? (
        <InlineEmpty align="center">{t.emptyRecallHint}</InlineEmpty>
      ) : (
        <>
          <ol className="flex flex-col gap-3">
            {visible.map((item, hi) => (
              <HitCard
                key={`${index}-${item.id}-${hi}`}
                item={item}
                rank={hi + 1}
                t={t}
              />
            ))}
          </ol>
          {hidden > 0 ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-fit"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll ? (
                <>
                  <ChevronUpIcon className="size-4" />
                  {t.collapseHidden.replace("{count}", String(hidden))}
                </>
              ) : (
                <>
                  <ChevronDownIcon className="size-4" />
                  {t.expandHidden.replace("{count}", String(hidden))}
                </>
              )}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}

export default function KnowledgeEvalPage() {
  const params = useParams<{ spaceId: string }>();
  const spaceId = params.spaceId;
  const { t } = useI18n();
  const [questions, setQuestions] = useState<string[]>(DEFAULT_QUESTIONS);
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<QuestionResult[] | null>(null);
  const [totalLatencyMs, setTotalLatencyMs] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [questionToDelete, setQuestionToDelete] = useState<number | null>(null);

  async function onRun() {
    const qs = questions.map((q) => q.trim()).filter(Boolean);
    if (qs.length === 0) {
      setError(t.knowledge.needQuestion);
      return;
    }
    setBusy(true);
    const wallStart = performance.now();
    try {
      const next: QuestionResult[] = [];
      for (const q of qs) {
        const t0 = performance.now();
        const res = await searchKnowledge({
          query: q,
          spaces: [spaceId],
          top_k: topK,
        });
        next.push({
          q,
          items: res.items ?? [],
          latencyMs: performance.now() - t0,
          traceId: res.trace_id,
        });
      }
      setResults(next);
      setTotalLatencyMs(performance.now() - wallStart);
      setError(null);
    } catch (e) {
      setResults(null);
      setTotalLatencyMs(0);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const totalHits = results?.reduce((n, r) => n + r.items.length, 0) ?? 0;
  const emptyQuestions =
    results?.filter((r) => r.items.length === 0).length ?? 0;
  const uniqueDocs = results
    ? new Set(
        results.flatMap(
          (r) =>
            r.items
              .map((i) => metaStr(i.metadata, "doc_id"))
              .filter(Boolean) as string[],
        ),
      ).size
    : 0;
  const avgLatency =
    results && results.length > 0
      ? results.reduce((n, r) => n + r.latencyMs, 0) / results.length
      : 0;
  const lowTop =
    results?.filter((r) => (r.items[0]?.score ?? 1) < LOW_SCORE).length ?? 0;

  function requestDeleteQuestion(index: number) {
    const text = questions[index]?.trim();
    if (text) {
      setQuestionToDelete(index);
      return;
    }
    setQuestions((prev) => prev.filter((_, i) => i !== index));
  }

  function confirmDeleteQuestion() {
    if (questionToDelete == null) return;
    setQuestions((prev) => prev.filter((_, i) => i !== questionToDelete));
    setQuestionToDelete(null);
  }

  return (
    <PageShell className="gap-5">
      <Header
        backHref={`/workspace/knowledge/${spaceId}`}
        title={t.knowledge.evalTitle}
        description={t.knowledge.evalDescription.replace(
          "{count}",
          String(PREVIEW_COUNT),
        )}
      />

      <AlertError>{error}</AlertError>

      <section className="bg-card flex flex-col gap-4 rounded-xl border p-5 shadow-xs">
        <div className="flex flex-col gap-2">
          {questions.map((q, index) => (
            <div key={index} className="flex items-center gap-2">
              <Input
                placeholder={t.knowledge.questionPlaceholder}
                value={q}
                onChange={(e) =>
                  setQuestions((prev) =>
                    prev.map((item, i) =>
                      i === index ? e.target.value : item,
                    ),
                  )
                }
              />
              <Tooltip content={t.knowledge.deleteQuestion}>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground shrink-0"
                  disabled={questions.length <= 1}
                  onClick={() => requestDeleteQuestion(index)}
                >
                  <Trash2Icon className="size-4" />
                  <span className="sr-only">{t.knowledge.deleteQuestion}</span>
                </Button>
              </Tooltip>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setQuestions((prev) => [...prev, ""])}
          >
            <PlusIcon className="size-4" />
            {t.knowledge.addQuestion}
          </Button>
          <label className="text-muted-foreground flex items-center gap-2 text-sm">
            {t.knowledge.topKPrefix}
            <Input
              type="number"
              min={1}
              max={50}
              className="h-9 w-16"
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value) || 5)}
            />
            {t.knowledge.topKSuffix}
          </label>
          <Button disabled={busy} onClick={() => void onRun()}>
            <PlayIcon className="size-4" />
            {busy ? t.knowledge.runningEval : t.knowledge.runEval}
          </Button>
        </div>
      </section>

      {results ? (
        <section className="flex flex-col gap-8">
          <div className="flex flex-wrap gap-2 text-xs">
            <Badge variant="outline">
              {t.knowledge.questionsCount.replace(
                "{count}",
                String(results.length),
              )}
            </Badge>
            <Badge variant="outline">
              {t.knowledge.totalLatency.replace(
                "{latency}",
                formatMs(totalLatencyMs),
              )}
            </Badge>
            <Badge variant="outline">
              {t.knowledge.avgLatency.replace(
                "{latency}",
                formatMs(avgLatency),
              )}
            </Badge>
            <Badge variant="outline">
              {t.knowledge.hitChunks.replace("{count}", String(totalHits))}
            </Badge>
            <Badge variant="outline">
              {t.knowledge.docsTouched.replace("{count}", String(uniqueDocs))}
            </Badge>
            {emptyQuestions > 0 ? (
              <Badge variant="destructive">
                {t.knowledge.emptyRecallCount.replace(
                  "{count}",
                  String(emptyQuestions),
                )}
              </Badge>
            ) : null}
            {lowTop > 0 ? (
              <Badge variant="secondary">
                {t.knowledge.lowTopCount.replace("{count}", String(lowTop))}
              </Badge>
            ) : null}
          </div>

          {results.map((r, qi) => (
            <QuestionBlock
              key={`${qi}-${r.q}`}
              result={r}
              index={qi}
              t={t.knowledge}
            />
          ))}
        </section>
      ) : null}

      <Dialog
        open={questionToDelete != null}
        onOpenChange={(open) => {
          if (!open) setQuestionToDelete(null);
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
              onClick={() => setQuestionToDelete(null)}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={confirmDeleteQuestion}
            >
              {t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}
