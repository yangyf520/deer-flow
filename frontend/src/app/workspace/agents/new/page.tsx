"use client";

import type { Message } from "@langchain/langgraph-sdk";
import {
  ArrowLeftIcon,
  BotIcon,
  CheckCircleIcon,
  InfoIcon,
  MoreHorizontalIcon,
  SaveIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  AGENT_SOUL_DRAFT_FORM_KEY,
  AGENT_SOUL_DRAFT_SOUL_KEY,
} from "@/components/workspace/agents/agents";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import type { Agent } from "@/core/agents";
import {
  AgentNameCheckError,
  AgentsApiDisabledError,
  checkAgentName,
  getAgent,
} from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { extractContentFromMessage } from "@/core/messages/utils";
import { safeLocalStorage } from "@/core/settings/local";
import { hasToolResult, useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

type Step = "name" | "chat";
type SetupAgentStatus = "idle" | "requested" | "completed";
type SoulDraftFinishStatus = "idle" | "requested" | "ready";

const NAME_RE = /^[A-Za-z0-9-]+$/;
const SAVE_HINT_STORAGE_KEY = "deerflow.agent-create.save-hint-seen";
const AGENT_READ_RETRY_DELAYS_MS = [200, 500, 1_000, 2_000];

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function getAgentWithRetry(agentName: string) {
  for (const delay of [0, ...AGENT_READ_RETRY_DELAYS_MS]) {
    if (delay > 0) {
      await wait(delay);
    }

    try {
      return await getAgent(agentName);
    } catch {
      // Retry until the write settles or the attempts are exhausted.
    }
  }

  return null;
}

function extractSoulMarkdown(text: string): string {
  const fenced = /```(?:markdown|md)?\s*([\s\S]*?)```/i.exec(text);
  if (fenced?.[1]) {
    return fenced[1].trim();
  }
  return text.trim();
}

function extractLatestAssistantSoul(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (!message || message.type !== "ai") continue;
    const text = extractContentFromMessage(message);
    if (!text.trim()) continue;
    return extractSoulMarkdown(text);
  }
  return "";
}

export default function NewAgentPage() {
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();

  const isDraft = searchParams.get("draft") === "1";
  const draftName = searchParams.get("name")?.trim() ?? "";
  const draftDescription = searchParams.get("description")?.trim() ?? "";

  const [step, setStep] = useState<Step>(
    isDraft && draftName ? "chat" : "name",
  );
  const [nameInput, setNameInput] = useState(draftName);
  const [nameError, setNameError] = useState("");
  const [isCheckingName, setIsCheckingName] = useState(false);
  const [agentName, setAgentName] = useState(isDraft ? draftName : "");
  const [agent, setAgent] = useState<Agent | null>(null);
  const [showSaveHint, setShowSaveHint] = useState(false);
  const [setupAgentStatus, setSetupAgentStatus] =
    useState<SetupAgentStatus>("idle");
  const [soulDraftFinishStatus, setSoulDraftFinishStatus] =
    useState<SoulDraftFinishStatus>("idle");
  const [soulDraftPreview, setSoulDraftPreview] = useState("");

  const draftStartedRef = useRef(false);
  const soulDraftFinishStatusRef = useRef<SoulDraftFinishStatus>("idle");
  const threadId = useMemo(() => uuid(), []);

  useEffect(() => {
    soulDraftFinishStatusRef.current = soulDraftFinishStatus;
  }, [soulDraftFinishStatus]);

  const { thread, sendMessage } = useThreadStream({
    threadId: undefined,
    context: {
      mode: "flash",
      is_bootstrap: true,
    },
    onFinish(state) {
      if (isDraft) {
        if (soulDraftFinishStatusRef.current !== "requested") {
          return;
        }
        const soul = extractLatestAssistantSoul(state.messages);
        if (!soul) {
          setSoulDraftFinishStatus("idle");
          toast.error(t.agents.soulDraftExtractError);
          return;
        }
        setSoulDraftPreview(soul);
        setSoulDraftFinishStatus("ready");
        return;
      }

      if (agent || setupAgentStatus !== "requested") {
        return;
      }
      if (!agentName || !hasToolResult(state.messages, "setup_agent")) {
        setSetupAgentStatus("idle");
        return;
      }
      setSetupAgentStatus("completed");
      void getAgentWithRetry(agentName).then((fetched) => {
        if (fetched) {
          setAgent(fetched);
          return;
        }

        toast.error(t.agents.agentCreatedPendingRefresh);
      });
    },
  });

  const startDraftChat = useCallback(async () => {
    if (!draftName || draftStartedRef.current) return;
    draftStartedRef.current = true;
    setAgentName(draftName);
    setStep("chat");

    const descriptionPart = draftDescription
      ? t.agents.soulDraftDescriptionPart.replace(
          "{description}",
          draftDescription,
        )
      : "";
    const text = t.agents.soulDraftBootstrapMessage
      .replace("{name}", draftName)
      .replace("{descriptionPart}", descriptionPart);

    await sendMessage(threadId, { text, files: [] }, { agent_name: draftName });
  }, [
    draftDescription,
    draftName,
    sendMessage,
    t.agents.soulDraftBootstrapMessage,
    t.agents.soulDraftDescriptionPart,
    threadId,
  ]);

  useEffect(() => {
    if (!isDraft || !draftName) return;
    void startDraftChat();
  }, [isDraft, draftName, startDraftChat]);

  useEffect(() => {
    if (typeof window === "undefined" || step !== "chat" || isDraft) {
      return;
    }
    if (safeLocalStorage.getItem(SAVE_HINT_STORAGE_KEY) === "1") {
      return;
    }
    setShowSaveHint(true);
    safeLocalStorage.setItem(SAVE_HINT_STORAGE_KEY, "1");
  }, [isDraft, step]);

  const handleConfirmName = useCallback(async () => {
    const trimmed = nameInput.trim();
    if (!trimmed) return;
    if (!NAME_RE.test(trimmed)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    setNameError("");
    setIsCheckingName(true);
    try {
      const result = await checkAgentName(trimmed);
      if (!result.available) {
        setNameError(t.agents.nameStepAlreadyExistsError);
        return;
      }
    } catch (err) {
      if (err instanceof AgentsApiDisabledError) {
        setNameError(t.agents.nameStepApiDisabledError);
      } else if (
        err instanceof AgentNameCheckError &&
        err.reason === "backend_unreachable"
      ) {
        setNameError(t.agents.nameStepNetworkError);
      } else if (
        err instanceof AgentNameCheckError &&
        err.reason === "request_failed"
      ) {
        setNameError(
          err.detail
            ? t.agents.nameStepCheckErrorWithDetail.replace(
                "{detail}",
                err.detail,
              )
            : t.agents.nameStepCheckError,
        );
      } else {
        setNameError(t.agents.nameStepCheckError);
      }
      return;
    } finally {
      setIsCheckingName(false);
    }

    setAgentName(trimmed);
    setStep("chat");
    await sendMessage(
      threadId,
      {
        text: t.agents.nameStepBootstrapMessage.replace("{name}", trimmed),
        files: [],
      },
      { agent_name: trimmed },
    );
  }, [
    nameInput,
    sendMessage,
    t.agents.nameStepAlreadyExistsError,
    t.agents.nameStepApiDisabledError,
    t.agents.nameStepNetworkError,
    t.agents.nameStepBootstrapMessage,
    t.agents.nameStepCheckError,
    t.agents.nameStepCheckErrorWithDetail,
    t.agents.nameStepInvalidError,
    threadId,
  ]);

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !isIMEComposing(e)) {
      e.preventDefault();
      void handleConfirmName();
    }
  };

  const handleChatSubmit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || thread.isLoading) return;
      await sendMessage(
        threadId,
        { text: trimmed, files: [] },
        { agent_name: agentName },
      );
    },
    [agentName, sendMessage, thread.isLoading, threadId],
  );

  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      if (!agentName) {
        return false;
      }

      let sent = false;
      await sendMessage(
        threadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        { agent_name: agentName },
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
      return sent;
    },
    [agentName, sendMessage, threadId],
  );

  const handleSaveAgent = useCallback(async () => {
    if (
      !agentName ||
      agent ||
      thread.isLoading ||
      setupAgentStatus !== "idle"
    ) {
      return;
    }

    setSetupAgentStatus("requested");
    setShowSaveHint(false);
    try {
      await sendMessage(
        threadId,
        { text: t.agents.saveCommandMessage, files: [] },
        { agent_name: agentName },
        { additionalKwargs: { hide_from_ui: true } },
      );
      toast.success(t.agents.saveRequested);
    } catch (error) {
      setSetupAgentStatus("idle");
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    agent,
    agentName,
    sendMessage,
    setupAgentStatus,
    t.agents.saveCommandMessage,
    t.agents.saveRequested,
    thread.isLoading,
    threadId,
  ]);

  const handleFinishSoulDraft = useCallback(async () => {
    if (
      !agentName ||
      thread.isLoading ||
      soulDraftFinishStatus !== "idle" ||
      soulDraftPreview
    ) {
      return;
    }

    setSoulDraftFinishStatus("requested");
    try {
      await sendMessage(
        threadId,
        { text: t.agents.soulDraftFinishMessage, files: [] },
        { agent_name: agentName },
        { additionalKwargs: { hide_from_ui: true } },
      );
    } catch (error) {
      setSoulDraftFinishStatus("idle");
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    agentName,
    sendMessage,
    soulDraftFinishStatus,
    soulDraftPreview,
    t.agents.soulDraftFinishMessage,
    thread.isLoading,
    threadId,
  ]);

  const handleConfirmSoulDraft = useCallback(() => {
    const trimmed = soulDraftPreview.trim();
    if (!trimmed) return;

    window.sessionStorage.setItem(AGENT_SOUL_DRAFT_SOUL_KEY, trimmed);

    let returnMode: "create" | "edit" = "create";
    const rawForm = window.sessionStorage.getItem(AGENT_SOUL_DRAFT_FORM_KEY);
    if (rawForm) {
      try {
        const parsed = JSON.parse(rawForm) as { mode?: "create" | "edit" };
        if (parsed.mode === "edit") {
          returnMode = "edit";
        }
      } catch {
        // Keep default create mode when form snapshot is malformed.
      }
    }

    if (returnMode === "edit") {
      router.push(`/workspace/agents?edit=${encodeURIComponent(agentName)}`);
      return;
    }
    router.push("/workspace/agents?create=1");
  }, [agentName, router, soulDraftPreview]);

  const handleBack = useCallback(() => {
    if (!isDraft) {
      router.push("/workspace/agents");
      return;
    }

    let returnMode: "create" | "edit" = "create";
    const rawForm = window.sessionStorage.getItem(AGENT_SOUL_DRAFT_FORM_KEY);
    if (rawForm) {
      try {
        const parsed = JSON.parse(rawForm) as { mode?: "create" | "edit" };
        if (parsed.mode === "edit") {
          returnMode = "edit";
        }
      } catch {
        // Keep default create mode when form snapshot is malformed.
      }
    }

    if (returnMode === "edit") {
      router.push(
        `/workspace/agents?edit=${encodeURIComponent(agentName || draftName)}`,
      );
      return;
    }
    router.push("/workspace/agents?create=1");
  }, [agentName, draftName, isDraft, router]);

  const pageTitle = isDraft
    ? t.agents.soulDraftPageTitle
    : t.agents.createPageTitle;

  const header = (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon-sm" onClick={handleBack}>
          <ArrowLeftIcon className="h-4 w-4" />
        </Button>
        <h1 className="text-sm font-semibold">{pageTitle}</h1>
      </div>

      {step === "chat" ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t.agents.more}>
              <MoreHorizontalIcon className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {isDraft ? (
              <DropdownMenuItem
                onSelect={() => void handleFinishSoulDraft()}
                disabled={[
                  Boolean(soulDraftPreview),
                  thread.isLoading,
                  soulDraftFinishStatus !== "idle",
                ].some(Boolean)}
              >
                <SaveIcon className="h-4 w-4" />
                {soulDraftFinishStatus === "requested"
                  ? t.agents.soulGenerating
                  : t.agents.soulDraftConfirm}
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem
                onSelect={() => void handleSaveAgent()}
                disabled={[
                  Boolean(agent),
                  thread.isLoading,
                  setupAgentStatus !== "idle",
                ].some(Boolean)}
              >
                <SaveIcon className="h-4 w-4" />
                {setupAgentStatus === "requested"
                  ? t.agents.saving
                  : t.agents.save}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </header>
  );

  if (step === "name") {
    return (
      <div className="flex size-full flex-col">
        {header}
        <main className="flex flex-1 flex-col items-center justify-center px-4">
          <div className="w-full max-w-sm space-y-8">
            <div className="space-y-3 text-center">
              <div className="bg-primary/10 mx-auto flex h-14 w-14 items-center justify-center rounded-full">
                <BotIcon className="text-primary h-7 w-7" />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-semibold">
                  {t.agents.nameStepTitle}
                </h2>
                <p className="text-muted-foreground text-sm">
                  {t.agents.nameStepHint}
                </p>
              </div>
            </div>

            <div className="space-y-3">
              <Input
                autoFocus
                placeholder={t.agents.nameStepPlaceholder}
                value={nameInput}
                onChange={(e) => {
                  setNameInput(e.target.value);
                  setNameError("");
                }}
                onKeyDown={handleNameKeyDown}
                className={cn(nameError && "border-destructive")}
              />
              {nameError ? (
                <p className="text-destructive text-sm">{nameError}</p>
              ) : null}
              <Button
                className="w-full"
                onClick={() => void handleConfirmName()}
                disabled={!nameInput.trim() || isCheckingName}
              >
                {t.agents.nameStepContinue}
              </Button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ArtifactsProvider>
        <div className="flex size-full flex-col">
          {header}

          <main className="flex min-h-0 flex-1 flex-col">
            {showSaveHint ? (
              <div className="px-4 pt-4">
                <div className="mx-auto w-full max-w-(--container-width-md)">
                  <Alert>
                    <InfoIcon className="h-4 w-4" />
                    <AlertDescription>{t.agents.saveHint}</AlertDescription>
                  </Alert>
                </div>
              </div>
            ) : null}

            <div className="flex min-h-0 flex-1 justify-center">
              <MessageList
                className={cn("size-full", showSaveHint ? "pt-4" : "pt-10")}
                threadId={threadId}
                thread={thread}
                onSubmitHumanInput={
                  agentName ? handleSubmitHumanInput : undefined
                }
              />
            </div>

            <div className="bg-background flex shrink-0 justify-center border-t px-4 py-4">
              <div className="w-full max-w-(--container-width-md)">
                {isDraft && soulDraftPreview ? (
                  <div className="flex flex-col gap-4 rounded-2xl border p-4">
                    <div className="space-y-1 text-center">
                      <CheckCircleIcon className="text-primary mx-auto h-8 w-8" />
                      <p className="font-semibold">
                        {t.agents.soulDraftConfirmTitle}
                      </p>
                      <p className="text-muted-foreground text-sm">
                        {t.agents.soulDraftConfirmHint}
                      </p>
                    </div>
                    <Textarea
                      value={soulDraftPreview}
                      onChange={(event) =>
                        setSoulDraftPreview(event.target.value)
                      }
                      className="min-h-48 font-mono text-sm"
                    />
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        onClick={() => {
                          setSoulDraftPreview("");
                          setSoulDraftFinishStatus("idle");
                        }}
                      >
                        {t.agents.soulDraftBackToChat}
                      </Button>
                      <Button onClick={handleConfirmSoulDraft}>
                        {t.agents.soulDraftReturn}
                      </Button>
                    </div>
                  </div>
                ) : agent ? (
                  <div className="flex flex-col items-center gap-4 rounded-2xl border py-8 text-center">
                    <CheckCircleIcon className="text-primary h-10 w-10" />
                    <p className="font-semibold">{t.agents.agentCreated}</p>
                    <div className="flex gap-2">
                      <Button
                        onClick={() =>
                          router.push(
                            `/workspace/agents/${agentName}/chats/new`,
                          )
                        }
                      >
                        {t.agents.startChatting}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => router.push("/workspace/agents")}
                      >
                        {t.agents.backToGallery}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <PromptInput
                    disabled={thread.isLoading}
                    onSubmit={({ text }) => void handleChatSubmit(text)}
                  >
                    <PromptInputTextarea
                      autoFocus
                      placeholder={
                        isDraft
                          ? t.agents.soulDraftChatPlaceholder
                          : t.agents.createPageSubtitle
                      }
                      disabled={thread.isLoading}
                    />
                    <PromptInputFooter className="justify-end">
                      <PromptInputSubmit disabled={thread.isLoading} />
                    </PromptInputFooter>
                  </PromptInput>
                )}
              </div>
            </div>
          </main>
        </div>
      </ArtifactsProvider>
    </ThreadContext.Provider>
  );
}
