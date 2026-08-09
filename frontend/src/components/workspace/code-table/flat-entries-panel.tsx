"use client";

import { SettingsIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  AlertError,
  CardAction,
  ConfirmDialog,
  HeaderCreateButton,
  InlineEmpty,
  ItemListPanel,
  ListPanelToolbar,
  ListSearchField,
  PanelEmpty,
  Shell,
  ShellHeader,
} from "@/components/component";
import {
  headerPairedActionButtonClass,
  workspacePageInsetXClass,
} from "@/components/component/styles";
import {
  CodeTableEntryCreateDialog,
  CodeTableEntryEditDialog,
} from "@/components/workspace/code-table/entry-dialog";
import { KnowledgeCatalogSections } from "@/components/workspace/knowledge/catalog-sections";
import {
  createCodeTableEntry,
  deleteCodeTableEntry,
  listCodeTableDomains,
  loadCodeTableBundle,
  updateCodeTableEntry,
  type CodeTableFlatBundle,
  type CodeTableFlatEntry,
} from "@/core/code-table/api";
import {
  attrsFromFormValues,
  flatEntryToEntry,
  flatEntryToIndustryTag,
  industryTagAttrFields,
  industryTagToEntry,
  type CodeTableEntryFormValues,
  type CodeTableEntryRecord,
} from "@/core/code-table/entry-schema";
import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeIndustryTag } from "@/core/knowledge/api";
import { cn } from "@/lib/utils";

const INDUSTRY_TYPE_KEY = "industry_tag";

export function FlatCodeTablePanel({
  domain,
  backHref,
}: {
  domain: string;
  backHref?: string;
}) {
  const { t, locale } = useI18n();
  const kb = t.knowledge;
  const ct = t.codeTable;
  const [typeKey, setTypeKey] = useState("");
  const [categoryLabel, setCategoryLabel] = useState("");
  const [entries, setEntries] = useState<CodeTableFlatEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [editing, setEditing] = useState<CodeTableEntryRecord | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [entryToDelete, setEntryToDelete] =
    useState<KnowledgeIndustryTag | null>(null);

  const entryAttrFields = useMemo(
    () => (typeKey === INDUSTRY_TYPE_KEY ? industryTagAttrFields(ct) : []),
    [ct, typeKey],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [domainsRes, bundle] = await Promise.all([
        listCodeTableDomains(),
        loadCodeTableBundle(domain),
      ]);
      const category = domainsRes.items.find((item) => item.domain === domain);
      const resolvedTypeKey = category?.type_key ?? "";
      setTypeKey(resolvedTypeKey);
      setCategoryLabel(category?.label?.trim() ?? domain);
      const flat = bundle as CodeTableFlatBundle;
      setEntries(
        flat.items.filter(
          (item) => !resolvedTypeKey || item.type_key === resolvedTypeKey,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [domain]);

  useEffect(() => {
    void reload();
  }, [reload, locale]);

  const industryTags = useMemo(
    () =>
      typeKey === INDUSTRY_TYPE_KEY
        ? entries.map((entry) => flatEntryToIndustryTag(entry))
        : [],
    [entries, typeKey],
  );

  const q = query.trim().toLowerCase();
  const filteredTags = useMemo(() => {
    if (!q) return industryTags;
    return industryTags.filter((tag) => {
      const label = (tag.label?.trim() ?? tag.id).toLowerCase();
      const keywords = (tag.keywords ?? []).join(" ").toLowerCase();
      const department = (tag.department ?? []).join(" ").toLowerCase();
      return (
        tag.id.toLowerCase().includes(q) ||
        label.includes(q) ||
        keywords.includes(q) ||
        department.includes(q)
      );
    });
  }, [industryTags, q]);

  const simpleRows = useMemo(() => {
    if (typeKey === INDUSTRY_TYPE_KEY) return [];
    const rows = entries.map((entry) => flatEntryToEntry(entry));
    if (!q) return rows;
    return rows.filter(
      (entry) =>
        entry.code.toLowerCase().includes(q) ||
        entry.label.toLowerCase().includes(q),
    );
  }, [entries, q, typeKey]);

  const isEmpty = !loading && entries.length === 0;
  const countLabel =
    entries.length > 0
      ? q
        ? kb.codeTableCountFiltered(
            typeKey === INDUSTRY_TYPE_KEY
              ? filteredTags.length
              : simpleRows.length,
            entries.length,
          )
        : kb.codeTableCountTotal(entries.length)
      : undefined;

  const headerSuffix = typeKey.length > 0 ? `${domain} · ${typeKey}` : domain;

  async function onCreateEntry(input: CodeTableEntryFormValues) {
    if (!typeKey) return;
    setCreateBusy(true);
    setError(null);
    try {
      await createCodeTableEntry(domain, {
        type_key: typeKey,
        code: input.code,
        label: input.label,
        attrs: attrsFromFormValues(input, entryAttrFields),
      });
      setCreateOpen(false);
      toast.success(ct.entryCreated);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreateBusy(false);
    }
  }

  async function onSaveEntry(input: Omit<CodeTableEntryFormValues, "code">) {
    if (!editing || !typeKey) return;
    setEditBusy(true);
    setError(null);
    try {
      await updateCodeTableEntry(domain, editing.code, {
        type_key: typeKey,
        label: input.label,
        attrs: attrsFromFormValues(
          { code: editing.code, label: input.label, attrs: input.attrs },
          entryAttrFields,
        ),
      });
      setEditing(null);
      toast.success(ct.entryUpdated);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditBusy(false);
    }
  }

  async function removeEntry(code: string) {
    if (!typeKey) return;
    setDeleteBusy(true);
    setError(null);
    try {
      await deleteCodeTableEntry(domain, code, typeKey);
      if (editing?.code === code) setEditing(null);
      setEntryToDelete(null);
      toast.success(ct.entryDeleted);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <>
      <Shell
        fillBody={isEmpty}
        header={
          <ShellHeader
            backHref={backHref}
            title={categoryLabel || domain}
            description={ct.description}
            descriptionSuffix={headerSuffix}
            actions={
              <HeaderCreateButton
                className={headerPairedActionButtonClass}
                onClick={() => setCreateOpen(true)}
                disabled={!typeKey || loading}
              >
                {ct.createEntry}
              </HeaderCreateButton>
            }
          />
        }
      >
        {error ? <AlertError>{error}</AlertError> : null}

        <ItemListPanel
          className={entries.length > 0 ? "flex-initial" : undefined}
          countLabel={countLabel}
          toolbar={
            entries.length > 0 ? (
              <ListPanelToolbar>
                <ListSearchField
                  value={query}
                  onChange={setQuery}
                  placeholder={kb.codeTableSearchPlaceholder}
                />
              </ListPanelToolbar>
            ) : undefined
          }
        >
          {loading ? (
            <PanelEmpty className="py-6">{t.common.loading}</PanelEmpty>
          ) : isEmpty ? (
            <PanelEmpty className="py-6">
              <p className="text-foreground font-medium">{ct.entriesEmpty}</p>
              <button
                type="button"
                className="text-primary mt-3 text-sm font-medium hover:underline"
                onClick={() => setCreateOpen(true)}
                disabled={!typeKey}
              >
                {ct.createEntry}
              </button>
            </PanelEmpty>
          ) : typeKey === INDUSTRY_TYPE_KEY ? (
            filteredTags.length === 0 ? (
              <InlineEmpty className="p-3">
                {kb.codeTableSearchEmpty}
              </InlineEmpty>
            ) : (
              <KnowledgeCatalogSections
                scope={{ industry_tags: filteredTags }}
                kb={kb}
                onEditIndustryTag={(tag) => setEditing(industryTagToEntry(tag))}
                onDeleteIndustryTag={setEntryToDelete}
                industryTagActionsBusy={deleteBusy || editBusy}
              />
            )
          ) : simpleRows.length === 0 ? (
            <InlineEmpty className="p-3">{kb.codeTableSearchEmpty}</InlineEmpty>
          ) : (
            <div className={cn(workspacePageInsetXClass, "py-1.5 pb-2")}>
              <ul className="flex flex-col gap-2">
                {simpleRows.map((entry) => (
                  <li
                    key={entry.code}
                    className="border-border/60 bg-muted/20 rounded-lg border px-3 py-2"
                  >
                    <div className="flex min-w-0 items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-foreground truncate text-sm font-medium">
                          {entry.label}
                        </div>
                        <div className="text-muted-foreground truncate font-mono text-xs">
                          {entry.code}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <CardAction
                          icon={SettingsIcon}
                          label={t.common.edit}
                          onClick={() => setEditing(entry)}
                          disabled={deleteBusy || editBusy}
                        />
                        <CardAction
                          icon={Trash2Icon}
                          label={t.common.delete}
                          onClick={() =>
                            setEntryToDelete(flatEntryToIndustryTag(entry))
                          }
                          disabled={deleteBusy || editBusy}
                        />
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </ItemListPanel>
      </Shell>

      <CodeTableEntryCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        busy={createBusy}
        attrFields={entryAttrFields}
        codeHint={ct.entryCodeHint}
        onConfirm={onCreateEntry}
      />

      <CodeTableEntryEditDialog
        open={editing != null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        entry={editing}
        busy={editBusy}
        deleteBusy={deleteBusy}
        attrFields={entryAttrFields}
        onConfirm={onSaveEntry}
        onDelete={async () => {
          if (editing) await removeEntry(editing.code);
        }}
      />

      <ConfirmDialog
        open={entryToDelete != null}
        onOpenChange={(open) => {
          if (!open) setEntryToDelete(null);
        }}
        title={t.common.delete}
        description={ct.deleteEntryConfirm}
        confirmLabel={deleteBusy ? t.common.loading : t.common.delete}
        confirmPending={deleteBusy}
        confirmVariant="destructive"
        onConfirm={() => {
          if (entryToDelete) void removeEntry(entryToDelete.id);
        }}
        onCancel={() => setEntryToDelete(null)}
      />
    </>
  );
}
