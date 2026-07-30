"use client";

/** Agent workspace UI — cards + create/edit dialog. Composed in `app/workspace/agents/page.tsx`. */

import {
  BookOpenIcon,
  BotIcon,
  BotOffIcon,
  CheckIcon,
  Loader2Icon,
  MessageSquareIcon,
  SettingsIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import { ScenarioSelect } from "@/app/workspace/knowledge/ui";
import {
  CardAction,
  ConfirmDialog,
  DialogFieldGrid,
  DialogFormSection,
  DialogInputField,
  DialogSelectField,
  DialogSlotField,
  DialogTextareaField,
  FormDialog,
  InlineEmpty,
  ItemCard,
  MetaPill,
  buildFormDialogEditResourceMeta,
  dialogSaveFooterProps,
  dialogInlineButtonClass,
  itemMetaTags,
} from "@/components/component";
import {
  dialogSecondaryButtonClass,
  selectTriggerWrapClass,
} from "@/components/component/styles";
import { Button } from "@/components/ui/button";
import type {
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
} from "@/core/agents";
import {
  AgentNameCheckError,
  AgentsApiDisabledError,
  checkAgentName,
  generateSoul,
  useCreateAgent,
  useDeleteAgent,
  useUpdateAgent,
} from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  accessLabel,
  boundScenarioType,
  listMySpaces,
  listScenarios,
  roleLabel,
  scenarioLabel,
  type Space,
} from "@/core/knowledge";
import { loadModels } from "@/core/models/api";
import { cn } from "@/lib/utils";

const NAME_RE = /^[A-Za-z0-9-]+$/;
const INHERIT_VALUE = "__inherit__";

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
  const bound = boundScenarioType(space);

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
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="truncate text-sm font-medium">{space.name}</span>
          {bound ? (
            <span className="text-muted-foreground text-xs">
              {scenarioLabel(bound, t.knowledge)}
            </span>
          ) : null}
          {space.description ? (
            <span className="text-muted-foreground line-clamp-1 text-sm">
              {space.description}
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
  const [agentName, setAgentName] = useState("");
  const [nameError, setNameError] = useState("");
  const [description, setDescription] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [knowledgeScenario, setKnowledgeScenario] = useState<string | null>(
    null,
  );
  const [soul, setSoul] = useState("");
  const [soulGenerating, setSoulGenerating] = useState(false);
  const [spaces, setSpaces] = useState<string[]>([]);
  const [models, setModels] = useState<
    Awaited<ReturnType<typeof loadModels>>["models"]
  >([]);
  const [scenarios, setScenarios] = useState<
    Awaited<ReturnType<typeof listScenarios>>["items"]
  >([]);

  useEffect(() => {
    if (!open) return;
    if (isCreate) {
      setAgentName("");
      setNameError("");
      setDescription("");
      setModel(null);
      setKnowledgeScenario(null);
      setSoul("");
      setSpaces([]);
      return;
    }
    if (!agent) return;
    setAgentName(agent.name);
    setNameError("");
    setDescription(agent.description ?? "");
    setModel(agent.model ?? null);
    setKnowledgeScenario(agent.knowledge_scenario ?? null);
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
    void listScenarios()
      .then((res) => setScenarios(res.items))
      .catch(() => setScenarios([]));
  }, [open]);

  const filteredSpaces = useMemo(() => {
    if (!knowledgeScenario) return availableSpaces;
    return availableSpaces.filter(
      (space) => boundScenarioType(space) === knowledgeScenario,
    );
  }, [availableSpaces, knowledgeScenario]);

  const visibleSpaceIds = useMemo(
    () => filteredSpaces.map((space) => space.id),
    [filteredSpaces],
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

  async function handleGenerateSoul() {
    const trimmedName = (agentName.trim() || agent?.name) ?? "";
    setSoulGenerating(true);
    try {
      const result = await generateSoul({
        name: trimmedName,
        description: description.trim(),
        soul: soul.trim(),
        locale,
        model_name: model ?? undefined,
      });
      setSoul(result.soul);
      toast.success(t.agents.soulGenerated);
    } catch (err) {
      if (err instanceof AgentsApiDisabledError) {
        toast.error(t.agents.nameStepApiDisabledError);
      } else {
        toast.error(
          err instanceof Error && err.message
            ? err.message
            : t.agents.soulGenerateError,
        );
      }
    } finally {
      setSoulGenerating(false);
    }
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
      knowledge_scenario: knowledgeScenario,
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
              disabled={soulGenerating || isPending}
              onClick={() => void handleGenerateSoul()}
            >
              {soulGenerating ? (
                <Loader2Icon className="size-3.5 animate-spin" />
              ) : (
                <SparklesIcon className="size-3.5" />
              )}
              {soulGenerating ? t.agents.soulGenerating : t.agents.soulGenerate}
            </Button>
          </div>
          <DialogTextareaField
            value={soul}
            onChange={setSoul}
            autoGrow
            placeholder={t.agents.soulHint}
            textareaClassName="font-mono"
            disabled={soulGenerating || isPending}
          />
        </DialogFormSection>

        <DialogFormSection title={t.agents.sectionCapability}>
          <DialogFieldGrid>
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
            <DialogSlotField label={t.agents.fieldKnowledgeScenario}>
              <ScenarioSelect
                value={knowledgeScenario ?? INHERIT_VALUE}
                onValueChange={(value) =>
                  setKnowledgeScenario(value === INHERIT_VALUE ? null : value)
                }
                scenarios={scenarios}
                disabled={isPending}
                className={cn("w-full", selectTriggerWrapClass)}
                placeholder={t.knowledge.selectScenario}
                inheritLabel={t.agents.scenarioInherit}
                inheritValue={INHERIT_VALUE}
              />
            </DialogSlotField>
          </DialogFieldGrid>
        </DialogFormSection>

        <DialogFormSection title={t.agents.knowledgeTitle}>
          <div className="flex items-center justify-between gap-3">
            {availableSpaces.length > 0 ? (
              <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                {t.agents.knowledgeBoundCount
                  .replace("{bound}", String(boundInView))
                  .replace("{total}", String(filteredSpaces.length))}
              </span>
            ) : (
              <span />
            )}
            {filteredSpaces.length > 0 ? (
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
          ) : knowledgeScenario && filteredSpaces.length === 0 ? (
            <InlineEmpty>
              <p>
                {t.agents.knowledgeScenarioEmpty.replace(
                  "{scenario}",
                  scenarioLabel(knowledgeScenario, t.knowledge),
                )}
              </p>
            </InlineEmpty>
          ) : (
            <ul className="grid max-h-48 gap-2 overflow-y-auto">
              {filteredSpaces.map((space) => (
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

  const spaceNameById = useMemo(
    () => new Map(spaces.map((s) => [s.id, s.name])),
    [spaces],
  );
  const knowledgeSpaces = agent.knowledge_spaces ?? [];

  const metaTags = useMemo(() => {
    const tags: Array<{ key: string; label: ReactNode }> = [];
    if (agent.model) {
      tags.push({ key: "model", label: agent.model });
    }
    for (const spaceId of knowledgeSpaces) {
      tags.push({
        key: spaceId,
        label: (
          <>
            <BookOpenIcon className="size-2.5 shrink-0 opacity-70" />
            <span className="max-w-32 truncate">
              {spaceNameById.get(spaceId) ?? spaceId}
            </span>
          </>
        ),
      });
    }
    return tags.length > 0 ? itemMetaTags(tags) : undefined;
  }, [agent.model, knowledgeSpaces, spaceNameById]);

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
