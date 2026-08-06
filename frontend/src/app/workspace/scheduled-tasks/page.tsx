"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  AlertError,
  FormField,
  ItemRowStatusBadge,
  ResourceList,
  ResourceRow,
  Section,
  Shell,
  ShellHeader,
  SplitView,
  itemRowStatusToneFromValue,
} from "@/components/component";
import { panelClass } from "@/components/component/styles";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateScheduledTask,
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  usePauseScheduledTask,
  useResumeScheduledTask,
  useScheduledTaskRuns,
  useScheduledTasks,
  useTriggerScheduledTask,
  useThreadScheduledTasks,
} from "@/core/scheduled-tasks/hooks";
import { RECIPES, type Recipe } from "@/core/scheduled-tasks/recipes";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

const NONE = "—";

function formatTimestamp(value: string | null, locale: string): string {
  if (!value) {
    return NONE;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  // Use a locale-aware short format like "2026-07-03 09:00". Future timestamps
  // (next_run_at) render as an absolute time, not a relative "ago" string.
  const intlLocale = locale === "zh-CN" ? "zh-CN" : "en-US";
  return new Intl.DateTimeFormat(intlLocale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function ScheduledTasksPage() {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const searchParams = useSearchParams();
  const threadId = searchParams.get("thread_id");
  const allTasksQuery = useScheduledTasks();
  const threadTasksQuery = useThreadScheduledTasks(threadId);
  const data = threadId ? threadTasksQuery.data : allTasksQuery.data;
  const queryError = threadId ? threadTasksQuery.error : allTasksQuery.error;
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [contextMode, setContextMode] = useState<
    "fresh_thread_per_run" | "reuse_thread"
  >(threadId ? "reuse_thread" : "fresh_thread_per_run");
  const [targetThreadId, setTargetThreadId] = useState(threadId ?? "");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [createSchedule, setCreateSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "",
  });
  const [statusFilter, setStatusFilter] = useState<
    "all" | "enabled" | "paused" | "running" | "completed" | "failed"
  >("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "once" | "cron">("all");
  const [formError, setFormError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [editSchedule, setEditSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
  });
  const [createNonce, setCreateNonce] = useState(0);
  const filteredData = (data ?? []).filter((task) => {
    const statusPass = statusFilter === "all" || task.status === statusFilter;
    const typePass = typeFilter === "all" || task.schedule_type === typeFilter;
    return statusPass && typePass;
  });
  const selectedTask =
    filteredData.find((task) => task.id === selectedTaskId) ?? filteredData[0];
  const taskRunsQuery = useScheduledTaskRuns(selectedTask?.id);
  const createTask = useCreateScheduledTask();
  const updateTask = useUpdateScheduledTask(selectedTask?.id ?? "");
  const pauseTask = usePauseScheduledTask();
  const resumeTask = useResumeScheduledTask();
  const triggerTask = useTriggerScheduledTask();
  const deleteTask = useDeleteScheduledTask();

  const scheduleTypeLabel = (v: string) =>
    v === "cron"
      ? st.scheduleType.cron
      : v === "once"
        ? st.scheduleType.once
        : v;
  const statusLabel = (v: string) =>
    (st.status as Record<string, string>)[v] ?? v;
  const contextModeLabel = (v: string) =>
    v === "fresh_thread_per_run"
      ? st.context.fresh
      : v === "reuse_thread"
        ? st.context.reuse
        : v;
  const runTriggerLabel = (v: string) =>
    (st.runTrigger as Record<string, string>)[v] ?? v;
  const runStatusLabel = (v: string) =>
    (st.runStatus as Record<string, string>)[v] ?? v;
  const taskSummary = (task: ScheduledTask) =>
    `${scheduleTypeLabel(task.schedule_type)} · ${statusLabel(task.status)}`;
  const applyRecipe = (recipe: Recipe) => {
    const labels = st.recipes[recipe.titleKey];
    setTitle(labels.title);
    setPrompt(recipe.prompt);
    setCreateSchedule(recipe.schedule);
    setContextMode("fresh_thread_per_run");
    setCreateNonce((n) => n + 1);
  };

  useEffect(() => {
    document.title = `${t.sidebar.scheduledTasks} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.scheduledTasks]);

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    const stillVisible = filteredData.some(
      (task) => task.id === selectedTaskId,
    );
    if (!stillVisible) {
      setSelectedTaskId(filteredData[0]?.id ?? null);
      setEditing(false);
    }
  }, [filteredData, selectedTaskId]);

  useEffect(() => {
    if (!selectedTask) {
      setEditing(false);
      return;
    }
    setEditTitle(selectedTask.title);
    setEditPrompt(selectedTask.prompt);
    const spec = selectedTask.schedule_spec as {
      cron?: string;
      run_at?: string;
    };
    setEditSchedule({
      schedule_type: selectedTask.schedule_type,
      schedule_spec: {
        cron: typeof spec.cron === "string" ? spec.cron : undefined,
        run_at: typeof spec.run_at === "string" ? spec.run_at : undefined,
      },
      timezone: selectedTask.timezone || "UTC",
    });
    // Depend on id only so a background refetch (same task, new object reference)
    // does not wipe edits in progress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTask?.id]);

  return (
    <>
      <Shell header={<ShellHeader title={t.sidebar.scheduledTasks} />}>
        <Card
          data-testid="scheduled-task-create-form"
          className={cn(panelClass, "gap-4 py-4")}
        >
          <CardHeader className="px-4 pb-0 sm:px-5">
            <CardTitle className="text-sm font-medium">
              {st.create.title}
            </CardTitle>
            <CardDescription>{st.recipes.label}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 px-4 sm:px-5">
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="schedule-recipes"
            >
              {RECIPES.map((recipe) => (
                <Button
                  key={recipe.id}
                  variant="secondary"
                  size="sm"
                  onClick={() => applyRecipe(recipe)}
                >
                  <span aria-hidden>{recipe.icon}</span>
                  {st.recipes[recipe.titleKey].title}
                </Button>
              ))}
            </div>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={contextMode}
              onValueChange={(value) => {
                if (
                  value === "fresh_thread_per_run" ||
                  value === "reuse_thread"
                ) {
                  setContextMode(value);
                }
              }}
            >
              <ToggleGroupItem value="fresh_thread_per_run">
                {st.context.fresh}
              </ToggleGroupItem>
              <ToggleGroupItem value="reuse_thread">
                {st.context.reuse}
              </ToggleGroupItem>
            </ToggleGroup>
            {contextMode === "reuse_thread" && (
              <FormField label={st.detail.thread}>
                <Input
                  value={targetThreadId}
                  onChange={(event) => setTargetThreadId(event.target.value)}
                  placeholder={st.context.threadIdPlaceholder}
                />
              </FormField>
            )}
            <FormField label={st.create.taskTitle}>
              <Input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={st.create.taskTitle}
              />
            </FormField>
            <FormField label={st.create.prompt}>
              <Textarea
                rows={3}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={st.create.prompt}
              />
            </FormField>
            <ScheduledTaskScheduleInput
              key={createNonce}
              initial={createSchedule}
              onChange={setCreateSchedule}
            />
            {formError && <AlertError>{formError}</AlertError>}
            <Button
              onClick={() => {
                const hasSchedule =
                  Boolean(createSchedule.schedule_spec.cron) ||
                  Boolean(createSchedule.schedule_spec.run_at);
                if (
                  !title ||
                  !prompt ||
                  !hasSchedule ||
                  (contextMode === "reuse_thread" && !targetThreadId)
                ) {
                  setFormError(st.create.fillRequired);
                  return;
                }
                setFormError(null);
                createTask.mutate(
                  {
                    context_mode: contextMode,
                    thread_id:
                      contextMode === "reuse_thread" ? targetThreadId : null,
                    title,
                    prompt,
                    schedule_type: createSchedule.schedule_type,
                    schedule_spec: createSchedule.schedule_spec,
                    timezone: createSchedule.timezone || "UTC",
                  },
                  {
                    onSuccess: () => {
                      // Clear the form so a follow-up task starts fresh.
                      setTitle("");
                      setPrompt("");
                      setTargetThreadId("");
                      setContextMode("fresh_thread_per_run");
                      setCreateSchedule({
                        schedule_type: "cron",
                        schedule_spec: { cron: "0 9 * * *" },
                        timezone: "",
                      });
                      setCreateNonce((n) => n + 1);
                    },
                  },
                );
              }}
              disabled={
                !title ||
                !prompt ||
                (!createSchedule.schedule_spec.cron &&
                  !createSchedule.schedule_spec.run_at) ||
                (contextMode === "reuse_thread" && !targetThreadId) ||
                createTask.isPending
              }
            >
              {st.create.submit}
            </Button>
          </CardContent>
        </Card>
        {threadId && (
          <p className="text-muted-foreground text-sm">
            {st.detail.filteredByThread.replace("{id}", threadId)}
          </p>
        )}
        {queryError ? (
          <AlertError data-testid="scheduled-task-load-error">
            {st.detail.loadFailed}: {queryError.message}
          </AlertError>
        ) : null}
        <Section
          eyebrow={st.filters.allStatuses}
          title={t.sidebar.scheduledTasks}
          description={String(filteredData.length)}
        >
          <div className="flex flex-col gap-3">
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              className="flex-wrap"
              value={statusFilter}
              onValueChange={(value) => {
                if (
                  value === "all" ||
                  value === "enabled" ||
                  value === "paused" ||
                  value === "running" ||
                  value === "completed" ||
                  value === "failed"
                ) {
                  setStatusFilter(value);
                }
              }}
            >
              <ToggleGroupItem value="all">
                {st.filters.allStatuses}
              </ToggleGroupItem>
              <ToggleGroupItem value="enabled">
                {st.filters.enabled}
              </ToggleGroupItem>
              <ToggleGroupItem value="paused">
                {st.filters.paused}
              </ToggleGroupItem>
              <ToggleGroupItem value="completed">
                {st.filters.completed}
              </ToggleGroupItem>
              <ToggleGroupItem value="failed">
                {st.filters.failed}
              </ToggleGroupItem>
            </ToggleGroup>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={typeFilter}
              onValueChange={(value) => {
                if (value === "all" || value === "once" || value === "cron") {
                  setTypeFilter(value);
                }
              }}
            >
              <ToggleGroupItem value="all">
                {st.filters.allTypes}
              </ToggleGroupItem>
              <ToggleGroupItem value="cron">{st.filters.cron}</ToggleGroupItem>
              <ToggleGroupItem value="once">{st.filters.once}</ToggleGroupItem>
            </ToggleGroup>
          </div>
        </Section>

        <SplitView
          primary={
            <Card className={cn(panelClass, "min-w-0 gap-0 py-0")}>
              <CardHeader className="border-border/40 border-b px-4 py-3.5">
                <CardTitle className="text-base font-semibold tracking-tight">
                  {st.filters.allStatuses}
                </CardTitle>
                <CardDescription className="text-xs tabular-nums">
                  {filteredData.length}
                </CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <ScrollArea className="max-h-[min(60vh,32rem)]">
                  <ResourceList data-testid="scheduled-task-list">
                    {filteredData.map((task) => {
                      const isSelected = selectedTask?.id === task.id;
                      return (
                        <ResourceRow
                          key={task.id}
                          title={task.title}
                          description={taskSummary(task)}
                          selected={isSelected}
                          onClick={() => setSelectedTaskId(task.id)}
                          data-testid={`scheduled-task-item-${task.id}`}
                        />
                      );
                    })}
                  </ResourceList>
                </ScrollArea>
              </CardContent>
            </Card>
          }
          secondary={
            <Card
              className={cn(panelClass, "min-w-0 gap-4 py-4")}
              data-testid="scheduled-task-detail"
            >
              {selectedTask ? (
                <CardContent className="flex flex-col gap-3 px-4 sm:px-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-base font-semibold">
                        {selectedTask.title}
                      </h2>
                      <ItemRowStatusBadge
                        className="mt-1"
                        tone={itemRowStatusToneFromValue(selectedTask.status)}
                      >
                        {statusLabel(selectedTask.status)}
                      </ItemRowStatusBadge>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing((value) => !value)}
                    >
                      {editing ? st.actions.cancelEdit : st.actions.edit}
                    </Button>
                  </div>
                  <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-muted-foreground text-xs">
                        {st.detail.contextMode}
                      </dt>
                      <dd>{contextModeLabel(selectedTask.context_mode)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground text-xs">
                        {st.detail.schedule}
                      </dt>
                      <dd>{scheduleTypeLabel(selectedTask.schedule_type)}</dd>
                    </div>
                    <div className="sm:col-span-2">
                      <dt className="text-muted-foreground text-xs">
                        {selectedTask.context_mode === "reuse_thread"
                          ? st.detail.thread
                          : st.detail.lastThread}
                      </dt>
                      <dd className="font-mono text-xs break-all">
                        {selectedTask.context_mode === "reuse_thread"
                          ? (selectedTask.thread_id ?? NONE)
                          : (selectedTask.last_thread_id ?? NONE)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground text-xs">
                        {st.detail.nextRun}
                      </dt>
                      <dd className="tabular-nums">
                        {formatTimestamp(selectedTask.next_run_at, locale)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground text-xs">
                        {st.detail.lastRun}
                      </dt>
                      <dd className="tabular-nums">
                        {formatTimestamp(selectedTask.last_run_at, locale)}
                      </dd>
                    </div>
                    {selectedTask.last_error ? (
                      <div className="sm:col-span-2">
                        <dt className="text-muted-foreground text-xs">
                          {st.detail.lastError}
                        </dt>
                        <dd className="text-destructive text-xs">
                          {selectedTask.last_error}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                  <Separator />
                  {editing ? (
                    <div className="flex flex-col gap-2 rounded-lg border p-3">
                      <FormField label={st.edit.titlePlaceholder}>
                        <Input
                          value={editTitle}
                          onChange={(event) => setEditTitle(event.target.value)}
                          placeholder={st.edit.titlePlaceholder}
                        />
                      </FormField>
                      <FormField label={st.edit.promptPlaceholder}>
                        <Textarea
                          rows={3}
                          value={editPrompt}
                          onChange={(event) =>
                            setEditPrompt(event.target.value)
                          }
                          placeholder={st.edit.promptPlaceholder}
                        />
                      </FormField>
                      <ScheduledTaskScheduleInput
                        key={selectedTask.id}
                        initial={editSchedule}
                        onChange={setEditSchedule}
                        scheduleTypeLocked
                      />
                      <Button
                        size="sm"
                        onClick={() =>
                          updateTask.mutate({
                            title: editTitle,
                            prompt: editPrompt,
                            schedule_spec: editSchedule.schedule_spec,
                            timezone: editSchedule.timezone || "UTC",
                          })
                        }
                        disabled={updateTask.isPending}
                      >
                        {st.edit.submit}
                      </Button>
                    </div>
                  ) : (
                    <p className="text-muted-foreground text-sm">
                      {selectedTask.prompt}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        selectedTask.status === "paused"
                          ? resumeTask.mutate(selectedTask.id)
                          : pauseTask.mutate(selectedTask.id)
                      }
                    >
                      {selectedTask.status === "paused"
                        ? st.actions.resume
                        : st.actions.pause}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => triggerTask.mutate(selectedTask.id)}
                    >
                      {st.actions.trigger}
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => setDeleteOpen(true)}
                    >
                      {st.actions.delete}
                    </Button>
                  </div>
                  <div data-testid="scheduled-task-runs" className="text-sm">
                    {(taskRunsQuery.data ?? []).length === 1
                      ? st.detail.runsCountOne.replace(
                          "{count}",
                          String((taskRunsQuery.data ?? []).length),
                        )
                      : st.detail.runsCount.replace(
                          "{count}",
                          String((taskRunsQuery.data ?? []).length),
                        )}
                  </div>
                  <ScrollArea className="max-h-48">
                    <div
                      className="flex flex-col gap-2 pr-3"
                      data-testid="scheduled-task-run-list"
                    >
                      {(taskRunsQuery.data ?? []).length > 0 ? (
                        (taskRunsQuery.data ?? []).map((run) => (
                          <div
                            key={run.id}
                            className="bg-muted/40 rounded-md border p-2.5 text-sm"
                          >
                            <div className="flex flex-wrap items-center gap-2 font-medium">
                              <span>{runTriggerLabel(run.trigger)}</span>
                              <ItemRowStatusBadge
                                tone={itemRowStatusToneFromValue(run.status)}
                              >
                                {runStatusLabel(run.status)}
                              </ItemRowStatusBadge>
                            </div>
                            <div className="text-muted-foreground text-xs">
                              {run.run_id ?? NONE}
                            </div>
                            <div className="text-muted-foreground text-xs">
                              {formatTimestamp(run.scheduled_for, locale)}
                            </div>
                            {run.error && (
                              <div className="text-destructive text-xs">
                                {run.error}
                              </div>
                            )}
                          </div>
                        ))
                      ) : (
                        <div className="text-muted-foreground text-sm">
                          {st.detail.noRuns}
                        </div>
                      )}
                    </div>
                  </ScrollArea>
                </CardContent>
              ) : (
                <CardContent className="text-muted-foreground px-4 text-sm sm:px-5">
                  {st.detail.noSelection}
                </CardContent>
              )}
            </Card>
          }
        />
      </Shell>

      {/* Delete confirm — follows the agent-card confirm pattern. */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{st.actions.delete}</DialogTitle>
            <DialogDescription>{st.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteTask.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (selectedTask) {
                  deleteTask.mutate(selectedTask.id, {
                    onSuccess: () => setDeleteOpen(false),
                  });
                }
              }}
              disabled={deleteTask.isPending}
            >
              {deleteTask.isPending ? t.common.loading : st.actions.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
