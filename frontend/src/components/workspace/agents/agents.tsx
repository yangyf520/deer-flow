"use client";

/** Agent workspace UI — cards + create/edit dialog. Composed in `app/workspace/agents/page.tsx`. */

import type { Message } from "@langchain/langgraph-sdk";
import {
  BookOpenIcon,
  BotIcon,
  BotOffIcon,
  CheckIcon,
  MessageSquareIcon,
  SettingsIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import {
  CardAction,
  ConfirmDialog,
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogSelectField,
  DialogShell,
  DialogTextareaField,
  FormDialog,
  InlineEmpty,
  ItemCard,
  MetaPill,
  buildFormDialogEditResourceMeta,
  dialogSaveFooterProps,
  dialogInlineButtonClass,
} from "@/components/component";
import { dialogSecondaryButtonClass } from "@/components/component/styles";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import type {
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
} from "@/core/agents";
import {
  AgentNameCheckError,
  AgentsApiDisabledError,
  checkAgentName,
  useCreateAgent,
  useDeleteAgent,
  useUpdateAgent,
} from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  accessLabel,
  listMySpaces,
  resolveSpaceDisplayLabel,
  roleLabel,
  spacePrimaryCode,
  spaceSecondaryDescription,
  type Space,
} from "@/core/knowledge";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { extractContentFromMessage } from "@/core/messages/utils";
import { loadModels } from "@/core/models/api";
import { useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";
import { cn } from "@/lib/utils";

const NAME_RE = /^[A-Za-z0-9-]+$/;
const INHERIT_VALUE = "__inherit__";

export const AGENT_SOUL_DRAFT_FORM_KEY = "deerflow:pending-agent-form";
export const AGENT_SOUL_DRAFT_SOUL_KEY = "deerflow:pending-agent-soul";

function extractSoulMarkdown(text: string): string {
  const fenced = /```(?:markdown|md)?\s*([\s\S]*?)```/i.exec(text);
  if (fenced?.[1]) {
    return fenced[1].trim();
  }
  return text.trim();
}

export function extractLatestAssistantSoul(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (!message || message.type !== "ai") continue;
    const text = extractContentFromMessage(message);
    if (!text.trim()) continue;
    return extractSoulMarkdown(text);
  }
  return "";
}

function extractFencedSoulFromMessages(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (!message || message.type !== "ai") continue;
    const text = extractContentFromMessage(message);
    const fenced = /```(?:markdown|md)?\s*([\s\S]*?)```/i.exec(text);
    if (fenced?.[1]?.trim()) {
      return fenced[1].trim();
    }
  }
  return "";
}

function latestAiMessage(messages: Message[]): Message | undefined {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message?.type === "ai") return message;
  }
  return undefined;
}

function latestAiStillAsking(message: Message): boolean {
  if (message.type !== "ai") return false;
  if (
    message.tool_calls?.some(
      (toolCall) => toolCall.name === "ask_clarification",
    )
  ) {
    return true;
  }
  const text = extractContentFromMessage(message).trim();
  if (!text) return false;
  const lastLine = text.split("\n").pop()?.trim() ?? "";
  return /[?？]\s*$/.test(lastLine);
}

function shouldAutoRequestSoulFinish(
  messages: Message[],
  userReplyCount: number,
): boolean {
  if (userReplyCount < 1) return false;
  const latestAi = latestAiMessage(messages);
  if (!latestAi) return false;
  if (extractFencedSoulFromMessages(messages)) return false;
  return !latestAiStillAsking(latestAi);
}

function resolveSoulDraftForReturn(
  preview: string,
  messages: Message[],
): string {
  const trimmedPreview = preview.trim();
  if (trimmedPreview) return trimmedPreview;
  return extractFencedSoulFromMessages(messages);
}

function newChatHref(agentName: string) {
  return `/workspace/agents/${encodeURIComponent(agentName)}/chats/new`;
}

export function useAccessibleSpaces() {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const res = await listMySpaces();
      setSpaces(res.items);
    } catch {
      setSpaces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { spaces, loading };
}

type SoulDraftFinishStatus = "idle" | "requested" | "ready";

function AgentSoulDraftChat({
  agentName,
  description,
  onConfirm,
  onSnapshotChange,
}: {
  agentName: string;
  description: string;
  onConfirm: (soul: string) => void;
  onSnapshotChange: (snapshot: {
    preview: string;
    messages: Message[];
  }) => void;
}) {
  const { t } = useI18n();
  const threadId = useMemo(() => uuid(), []);
  const draftStartedRef = useRef(false);
  const soulDraftFinishStatusRef = useRef<SoulDraftFinishStatus>("idle");
  const autoFinishRequestedRef = useRef(false);
  const userReplyCountRef = useRef(0);
  const requestSoulFinishRef = useRef<(() => Promise<void>) | null>(null);

  const [soulDraftFinishStatus, setSoulDraftFinishStatus] =
    useState<SoulDraftFinishStatus>("idle");
  const [soulDraftPreview, setSoulDraftPreview] = useState("");

  useEffect(() => {
    soulDraftFinishStatusRef.current = soulDraftFinishStatus;
  }, [soulDraftFinishStatus]);

  const { thread, sendMessage } = useThreadStream({
    threadId: undefined,
    context: {
      mode: "flash",
    },
    onFinish(state) {
      const fencedSoul = extractFencedSoulFromMessages(state.messages);
      if (fencedSoul) {
        setSoulDraftPreview(fencedSoul);
        setSoulDraftFinishStatus("ready");
        return;
      }

      if (soulDraftFinishStatusRef.current === "requested") {
        const soul = extractLatestAssistantSoul(state.messages);
        if (!soul) {
          setSoulDraftFinishStatus("idle");
          autoFinishRequestedRef.current = false;
          toast.error(t.agents.soulDraftExtractError);
          return;
        }
        setSoulDraftPreview(soul);
        setSoulDraftFinishStatus("ready");
        return;
      }

      if (
        soulDraftFinishStatusRef.current === "idle" &&
        !autoFinishRequestedRef.current &&
        shouldAutoRequestSoulFinish(state.messages, userReplyCountRef.current)
      ) {
        autoFinishRequestedRef.current = true;
        void requestSoulFinishRef.current?.();
      }
    },
  });

  const requestSoulFinish = useCallback(async () => {
    if (
      !agentName ||
      thread.isLoading ||
      soulDraftPreview ||
      soulDraftFinishStatusRef.current === "requested"
    ) {
      return;
    }

    setSoulDraftFinishStatus("requested");
    try {
      await sendMessage(
        threadId,
        { text: t.agents.soulDraftFinishMessage, files: [] },
        undefined,
        { additionalKwargs: { hide_from_ui: true } },
      );
    } catch (error) {
      setSoulDraftFinishStatus("idle");
      autoFinishRequestedRef.current = false;
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    agentName,
    sendMessage,
    soulDraftPreview,
    t.agents.soulDraftFinishMessage,
    thread.isLoading,
    threadId,
  ]);

  useEffect(() => {
    requestSoulFinishRef.current = requestSoulFinish;
  }, [requestSoulFinish]);

  const startDraftChat = useCallback(async () => {
    if (!agentName || draftStartedRef.current) return;
    draftStartedRef.current = true;

    const descriptionPart = description
      ? t.agents.soulDraftDescriptionPart.replace("{description}", description)
      : "";
    const text = t.agents.soulDraftBootstrapMessage
      .replace("{name}", agentName)
      .replace("{descriptionPart}", descriptionPart);

    await sendMessage(threadId, { text, files: [] });
  }, [
    agentName,
    description,
    sendMessage,
    t.agents.soulDraftBootstrapMessage,
    t.agents.soulDraftDescriptionPart,
    threadId,
  ]);

  useEffect(() => {
    void startDraftChat();
  }, [startDraftChat]);

  const handleChatSubmit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || thread.isLoading) return;
      userReplyCountRef.current += 1;
      await sendMessage(threadId, { text: trimmed, files: [] });
    },
    [sendMessage, thread.isLoading, threadId],
  );

  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      let sent = false;
      await sendMessage(
        threadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        undefined,
        {
          additionalKwargs: {
            hide_from_ui: true,
            human_input_response: response,
          },
          onSent: () => {
            sent = true;
          },
        },
      );
      if (sent) {
        userReplyCountRef.current += 1;
      }
      return sent;
    },
    [sendMessage, threadId],
  );

  useEffect(() => {
    onSnapshotChange({
      preview: soulDraftPreview,
      messages: thread.messages,
    });
  }, [onSnapshotChange, soulDraftPreview, thread.messages]);

  const handleConfirmSoulDraft = useCallback(() => {
    const trimmed = soulDraftPreview.trim();
    if (!trimmed) return;
    onConfirm(trimmed);
  }, [onConfirm, soulDraftPreview]);

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ArtifactsProvider>
        <div className="flex min-h-[min(62vh,32rem)] flex-col">
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border">
            {soulDraftPreview ? (
              <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3">
                <div className="flex shrink-0 items-center justify-between gap-3">
                  <p className="text-sm font-medium">
                    {t.agents.soulDraftConfirmTitle}
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    onClick={handleConfirmSoulDraft}
                  >
                    {t.agents.soulDraftReturn}
                  </Button>
                </div>
                <Textarea
                  value={soulDraftPreview}
                  onChange={(event) => setSoulDraftPreview(event.target.value)}
                  className="field-sizing-fixed min-h-0 flex-1 resize-none overflow-y-auto font-mono text-xs leading-relaxed"
                />
              </div>
            ) : (
              <>
                <MessageList
                  className="min-h-0 flex-1 pt-2"
                  threadId={threadId}
                  thread={thread}
                  onSubmitHumanInput={handleSubmitHumanInput}
                  enableSidecarActions={false}
                />

                <div className="bg-background shrink-0 border-t px-3 py-2">
                  {soulDraftFinishStatus === "requested" ? (
                    <p className="text-muted-foreground py-1 text-center text-sm">
                      {t.agents.soulGenerating}
                    </p>
                  ) : (
                    <PromptInput
                      disabled={thread.isLoading}
                      onSubmit={({ text }) => void handleChatSubmit(text)}
                    >
                      <PromptInputTextarea
                        autoFocus
                        placeholder={t.agents.soulDraftChatPlaceholder}
                        disabled={thread.isLoading}
                      />
                      <PromptInputFooter className="justify-end">
                        <PromptInputSubmit disabled={thread.isLoading} />
                      </PromptInputFooter>
                    </PromptInput>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </ArtifactsProvider>
    </ThreadContext.Provider>
  );
}

function AgentSoulDraftDialog({
  open,
  onOpenChange,
  agentName,
  description,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName: string;
  description: string;
  onConfirm: (soul: string) => void;
}) {
  const { t } = useI18n();
  const [sessionKey, setSessionKey] = useState(0);
  const snapshotRef = useRef<{ preview: string; messages: Message[] }>({
    preview: "",
    messages: [],
  });
  const appliedOnCloseRef = useRef(false);

  useEffect(() => {
    if (open) {
      setSessionKey((key) => key + 1);
      snapshotRef.current = { preview: "", messages: [] };
      appliedOnCloseRef.current = false;
    }
  }, [open]);

  const handleSnapshotChange = useCallback(
    (snapshot: { preview: string; messages: Message[] }) => {
      snapshotRef.current = snapshot;
    },
    [],
  );

  const handleConfirm = useCallback(
    (soul: string) => {
      appliedOnCloseRef.current = true;
      onConfirm(soul);
      onOpenChange(false);
    },
    [onConfirm, onOpenChange],
  );

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        if (!appliedOnCloseRef.current) {
          const soul = resolveSoulDraftForReturn(
            snapshotRef.current.preview,
            snapshotRef.current.messages,
          );
          if (soul) {
            onConfirm(soul);
          }
        }
        appliedOnCloseRef.current = false;
      }
      onOpenChange(next);
    },
    [onConfirm, onOpenChange],
  );

  return (
    <DialogShell
      open={open}
      onOpenChange={handleOpenChange}
      title={t.agents.soulDraftPageTitle}
      bodyClassName={cn(
        "flex min-h-0 flex-1 flex-col gap-0 overflow-hidden pt-0",
      )}
      contentClassName="flex max-h-[min(92vh,52rem)] flex-col gap-2 p-4 sm:max-w-[52rem] sm:p-5"
    >
      {open ? (
        <AgentSoulDraftChat
          key={sessionKey}
          agentName={agentName}
          description={description}
          onConfirm={handleConfirm}
          onSnapshotChange={handleSnapshotChange}
        />
      ) : null}
    </DialogShell>
  );
}

function SpaceMountRow({
  space,
  selected,
  onToggle,
}: {
  space: Space;
  selected: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const access = accessLabel(space.access, t.knowledge);
  const role = space.my_role ? roleLabel(space.my_role, t.knowledge) : null;
  const primary = spacePrimaryCode(space);
  const secondary = spaceSecondaryDescription(space, primary);

  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl border px-3.5 py-3 text-left transition-colors",
        selected
          ? "border-primary/50 bg-primary/5"
          : "border-border/80 hover:bg-muted/40",
      )}
    >
      <span
        className={cn(
          "flex size-5 shrink-0 items-center justify-center rounded-md border",
          selected
            ? "border-primary bg-primary text-primary-foreground"
            : "border-muted-foreground/30",
        )}
        aria-hidden
      >
        {selected ? <CheckIcon className="size-3.5" /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span
          className="flex min-w-0 items-baseline gap-x-2"
          title={secondary ? `${primary} — ${secondary}` : primary}
        >
          <span className="truncate font-mono text-sm font-medium">
            {primary}
          </span>
          {secondary ? (
            <span className="text-muted-foreground truncate text-sm">
              {secondary}
            </span>
          ) : null}
        </span>
      </span>
      <span className="text-muted-foreground shrink-0 text-right text-xs">
        {access}
        {role ? ` · ${role}` : null}
      </span>
    </button>
  );
}

/** Create / edit agent — FormDialog with model and knowledge binding. */
export function AgentFormDialog({
  open,
  onOpenChange,
  mode,
  agent,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "create" | "edit";
  agent?: Agent | null;
}) {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const createAgent = useCreateAgent();
  const updateAgent = useUpdateAgent();
  const deleteAgent = useDeleteAgent();
  const { spaces: availableSpaces, loading: spacesLoading } =
    useAccessibleSpaces();

  const isCreate = mode === "create";
  const isPending =
    createAgent.isPending || updateAgent.isPending || deleteAgent.isPending;

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [soulDraftOpen, setSoulDraftOpen] = useState(false);
  const [agentName, setAgentName] = useState("");
  const [nameError, setNameError] = useState("");
  const [description, setDescription] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [soul, setSoul] = useState("");
  const [spaces, setSpaces] = useState<string[]>([]);
  const [models, setModels] = useState<
    Awaited<ReturnType<typeof loadModels>>["models"]
  >([]);

  useEffect(() => {
    if (!open) return;

    if (isCreate) {
      setAgentName("");
      setNameError("");
      setDescription("");
      setModel(null);
      setSoul("");
      setSpaces([]);
      return;
    }
    if (!agent) return;
    setAgentName(agent.name);
    setNameError("");
    setDescription(agent.description ?? "");
    setModel(agent.model ?? null);
    setSoul(agent.soul ?? "");
    setSpaces(
      Array.isArray(agent.knowledge_spaces) ? [...agent.knowledge_spaces] : [],
    );
  }, [open, isCreate, agent]);

  useEffect(() => {
    if (!open) return;
    void loadModels()
      .then((res) => setModels(res.models))
      .catch(() => setModels([]));
  }, [open]);

  const visibleSpaceIds = useMemo(
    () => availableSpaces.map((space) => space.id),
    [availableSpaces],
  );

  const boundInView = visibleSpaceIds.filter((id) =>
    spaces.includes(id),
  ).length;
  const allVisibleMounted =
    visibleSpaceIds.length > 0 && boundInView === visibleSpaceIds.length;

  function toggleSpace(spaceId: string) {
    setSpaces((prev) =>
      prev.includes(spaceId)
        ? prev.filter((id) => id !== spaceId)
        : [...prev, spaceId],
    );
  }

  function toggleAllMounted() {
    if (allVisibleMounted) {
      const visible = new Set(visibleSpaceIds);
      setSpaces((prev) => prev.filter((id) => !visible.has(id)));
      return;
    }
    setSpaces((prev) => [...new Set([...prev, ...visibleSpaceIds])]);
  }

  function handleOpenSoulGenerate() {
    const trimmedName = agentName.trim();
    if (!trimmedName || !NAME_RE.test(trimmedName)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    setSoulDraftOpen(true);
  }

  function handleSoulDraftConfirm(generatedSoul: string) {
    setSoul(generatedSoul);
    toast.success(t.agents.soulGenerated);
  }

  async function handleSave() {
    const trimmedName = agentName.trim();
    if (!trimmedName || !NAME_RE.test(trimmedName)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    if (isCreate) {
      try {
        const result = await checkAgentName(trimmedName);
        if (!result.available) {
          setNameError(t.agents.nameStepAlreadyExistsError);
          return;
        }
      } catch (err) {
        if (err instanceof AgentsApiDisabledError) {
          toast.error(t.agents.nameStepApiDisabledError);
        } else if (
          err instanceof AgentNameCheckError &&
          err.reason === "backend_unreachable"
        ) {
          toast.error(t.agents.nameStepNetworkError);
        } else {
          toast.error(t.agents.nameStepCheckError);
        }
        return;
      }
    }

    setNameError("");
    const payload = {
      description: description.trim(),
      model,
      soul,
      knowledge_spaces: spaces,
    };

    try {
      if (isCreate) {
        const request: CreateAgentRequest = { name: trimmedName, ...payload };
        await createAgent.mutateAsync(request);
        toast.success(t.agents.createSuccess);
        onOpenChange(false);
        return;
      }

      if (!agent) return;
      const request: UpdateAgentRequest = payload;
      await updateAgent.mutateAsync({ name: agent.name, request });
      toast.success(t.agents.settingsSaved);
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDelete() {
    if (!agent) return;
    try {
      await deleteAgent.mutateAsync(agent.name);
      toast.success(t.agents.deleteSuccess);
      setDeleteOpen(false);
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const title = isCreate ? t.agents.createPageTitle : t.agents.editPageTitle;

  return (
    <>
      <FormDialog
        open={open}
        onOpenChange={onOpenChange}
        title={title}
        editResourceMeta={buildFormDialogEditResourceMeta(
          isCreate ? null : agent,
          locale,
          user,
        )}
        {...dialogSaveFooterProps(t.common, {
          busy: isPending,
          disabled: !agentName.trim(),
        })}
        onConfirm={() => void handleSave()}
        leadingDestructive={
          isCreate || !agent
            ? undefined
            : {
                label: t.agents.delete,
                onClick: () => setDeleteOpen(true),
                disabled: isPending,
              }
        }
      >
        <DialogFormSection title={t.agents.sectionBasic}>
          <DialogFieldGrid>
            <DialogInputField
              label={t.agents.fieldName}
              value={agentName}
              onChange={(value) => {
                setAgentName(value);
                setNameError("");
              }}
              placeholder={t.agents.settingsNamePlaceholder}
              inputClassName="font-mono"
              error={nameError || undefined}
              spellCheck={false}
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="off"
              autoFocus={open && isCreate}
              disabled={isPending || !isCreate}
            />
            <DialogInputField
              label={t.agents.fieldDescription}
              value={description}
              onChange={setDescription}
              placeholder={t.agents.descriptionPlaceholder}
              disabled={isPending}
            />
          </DialogFieldGrid>
        </DialogFormSection>

        <DialogFormSection title={t.agents.soulTitle}>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-muted-foreground text-xs leading-snug">
              {t.agents.soulGenerateHint}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className={dialogInlineButtonClass}
              disabled={isPending}
              onClick={handleOpenSoulGenerate}
            >
              <SparklesIcon className="size-3.5" />
              {t.agents.soulGenerate}
            </Button>
          </div>
          <DialogTextareaField
            value={soul}
            onChange={setSoul}
            autoGrow
            placeholder={t.agents.soulHint}
            textareaClassName="font-mono"
            disabled={isPending}
          />
        </DialogFormSection>

        <DialogFormSection title={t.agents.sectionCapability}>
          <DialogSelectField
            label={t.agents.fieldModel}
            value={model ?? INHERIT_VALUE}
            onValueChange={(value) =>
              setModel(value === INHERIT_VALUE ? null : value)
            }
            placeholder={t.agents.modelInherit}
            disabled={isPending}
            options={[
              { value: INHERIT_VALUE, label: t.agents.modelInherit },
              ...models.map((item) => ({
                value: item.name,
                label: item.display_name ?? item.name,
              })),
            ]}
          />
        </DialogFormSection>

        <DialogFormSection title={t.agents.knowledgeTitle}>
          <div className="flex items-center justify-between gap-3">
            {availableSpaces.length > 0 ? (
              <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                {t.agents.knowledgeBoundCount
                  .replace("{bound}", String(boundInView))
                  .replace("{total}", String(availableSpaces.length))}
              </span>
            ) : (
              <span />
            )}
            {availableSpaces.length > 0 ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className={cn(dialogSecondaryButtonClass, "h-8 shrink-0")}
                onClick={toggleAllMounted}
                disabled={isPending}
              >
                {allVisibleMounted
                  ? t.agents.unmountAllOpen
                  : t.agents.mountAllOpen}
              </Button>
            ) : null}
          </div>

          {spacesLoading ? (
            <p className="text-muted-foreground text-sm">{t.common.loading}</p>
          ) : availableSpaces.length === 0 ? (
            <InlineEmpty className="flex flex-col items-start gap-3">
              <p>{t.agents.knowledgeEmptyHint}</p>
              <Button asChild size="sm" variant="outline">
                <Link href="/workspace/knowledge">
                  <BookOpenIcon />
                  {t.agents.openKnowledge}
                </Link>
              </Button>
            </InlineEmpty>
          ) : (
            <ul className="grid max-h-48 gap-2 overflow-y-auto">
              {availableSpaces.map((space) => (
                <li key={space.id}>
                  <SpaceMountRow
                    space={space}
                    selected={spaces.includes(space.id)}
                    onToggle={() => toggleSpace(space.id)}
                  />
                </li>
              ))}
            </ul>
          )}
        </DialogFormSection>
      </FormDialog>

      {!isCreate && agent ? (
        <ConfirmDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          description={t.common.deleteConfirm}
          confirmLabel={
            deleteAgent.isPending ? t.common.loading : t.common.delete
          }
          confirmPending={deleteAgent.isPending}
          onConfirm={() => void handleDelete()}
          onCancel={() => setDeleteOpen(false)}
        />
      ) : null}

      <AgentSoulDraftDialog
        open={soulDraftOpen}
        onOpenChange={setSoulDraftOpen}
        agentName={agentName.trim()}
        description={description.trim()}
        onConfirm={handleSoulDraftConfirm}
      />
    </>
  );
}

interface AgentCardProps {
  agent: Agent;
  spaces?: Space[];
  onEdit?: (agent: Agent) => void;
}

export function AgentCard({ agent, spaces = [], onEdit }: AgentCardProps) {
  const { t } = useI18n();
  const chatHref = newChatHref(agent.name);

  const metaTags = useMemo(() => {
    const knowledgeSpaces = agent.knowledge_spaces ?? [];
    const tags: Array<{ key: string; label: ReactNode }> = [];
    for (const spaceId of knowledgeSpaces) {
      const label = resolveSpaceDisplayLabel(spaceId, spaces);
      tags.push({
        key: `space:${spaceId}`,
        label: (
          <>
            <BookOpenIcon className="size-2.5 shrink-0 opacity-70" />
            <span className="min-w-0 truncate" title={label}>
              {label}
            </span>
          </>
        ),
      });
    }
    if (tags.length === 0) return undefined;
    return tags.map(({ key, label }) => (
      <MetaPill key={key} mono className="w-full min-w-0 whitespace-nowrap">
        {label}
      </MetaPill>
    ));
  }, [agent.knowledge_spaces, spaces]);

  return (
    <ItemCard
      icon={BotIcon}
      iconTone="agent"
      title={
        <MetaPill
          mono
          variant="plain"
          className="text-foreground font-semibold"
        >
          {agent.name}
        </MetaPill>
      }
      description={agent.description ?? undefined}
      metaTags={metaTags}
      metaTagsLayout="inline-nowrap"
      href={chatHref}
      actions={
        <>
          <CardAction
            href={chatHref}
            icon={MessageSquareIcon}
            label={t.agents.chat}
          />
          <CardAction
            icon={SettingsIcon}
            label={t.common.edit}
            onClick={() => onEdit?.(agent)}
          />
        </>
      }
    />
  );
}

export function AgentsFeatureDisabled() {
  const { t } = useI18n();
  return (
    <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
        <BotOffIcon className="text-muted-foreground h-7 w-7" />
      </div>
      <div>
        <p className="font-medium">{t.agents.featureDisabledTitle}</p>
        <p className="text-muted-foreground mt-1 max-w-md text-sm">
          {t.agents.featureDisabledDescription}
        </p>
      </div>
    </div>
  );
}
