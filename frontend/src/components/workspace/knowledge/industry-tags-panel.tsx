"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  AlertError,
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
import { headerPairedActionButtonClass } from "@/components/component/styles";
import {
  CodeTableEntryCreateDialog,
  CodeTableEntryEditDialog,
} from "@/components/workspace/code-table/entry-dialog";
import { KnowledgeCatalogSections } from "@/components/workspace/knowledge/catalog-sections";
import { loadKnowledgeCodeTable } from "@/core/code-table/api";
import type { KnowledgeCodeTable } from "@/core/code-table/api";
import {
  industryTagAttrFields,
  industryTagToEntry,
  type CodeTableEntryFormValues,
} from "@/core/code-table/entry-schema";
import { useI18n } from "@/core/i18n/hooks";
import {
  deleteIndustryTag,
  upsertIndustryTag,
  type KnowledgeIndustryTag,
} from "@/core/knowledge";

export function IndustryTagsPanel({ backHref }: { backHref?: string }) {
  const { t, locale } = useI18n();
  const kb = t.knowledge;
  const ct = t.codeTable;
  const entryAttrFields = useMemo(() => industryTagAttrFields(ct), [ct]);
  const [codeTable, setCodeTable] = useState<KnowledgeCodeTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [editing, setEditing] = useState<KnowledgeIndustryTag | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [tagToDelete, setTagToDelete] = useState<KnowledgeIndustryTag | null>(
    null,
  );

  const reload = useCallback(async () => {
    try {
      const codeTableRes = await loadKnowledgeCodeTable();
      setCodeTable(codeTableRes);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, locale]);

  const industryTags = codeTable?.industry_tags ?? [];

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

  const displayScope = useMemo(
    () => ({ industry_tags: filteredTags }),
    [filteredTags],
  );

  const countLabel = useMemo(() => {
    if (industryTags.length === 0) return undefined;
    if (q)
      return kb.codeTableCountFiltered(
        filteredTags.length,
        industryTags.length,
      );
    return kb.codeTableCountTotal(industryTags.length);
  }, [filteredTags.length, industryTags.length, kb, q]);

  const isEmpty = industryTags.length === 0 && !error && codeTable !== null;

  async function onCreateEntry(input: CodeTableEntryFormValues) {
    setCreateBusy(true);
    setError(null);
    try {
      await upsertIndustryTag(input.code, {
        code: input.code,
        label: input.label,
        keywords: input.attrs.keywords ?? [],
        department: input.attrs.department ?? [],
        aliases: input.attrs.aliases ?? [],
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
    if (!editing) return;
    setEditBusy(true);
    setError(null);
    try {
      await upsertIndustryTag(editing.id, {
        code: editing.id,
        label: input.label,
        keywords: input.attrs.keywords ?? [],
        department: input.attrs.department ?? [],
        aliases: input.attrs.aliases ?? [],
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

  async function removeIndustryTag(target: KnowledgeIndustryTag) {
    setDeleteBusy(true);
    setError(null);
    try {
      await deleteIndustryTag(target.id);
      if (editing?.id === target.id) setEditing(null);
      setTagToDelete(null);
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
            title={kb.codeTableTitle}
            description={kb.codeTableDescription}
            actions={
              <HeaderCreateButton
                className={headerPairedActionButtonClass}
                onClick={() => setCreateOpen(true)}
              >
                {ct.createEntry}
              </HeaderCreateButton>
            }
          />
        }
      >
        {error ? <AlertError>{error}</AlertError> : null}

        <ItemListPanel
          className={industryTags.length > 0 ? "flex-initial" : undefined}
          countLabel={countLabel}
          toolbar={
            industryTags.length > 0 ? (
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
          {codeTable === null && !error ? (
            <PanelEmpty className="py-6">{t.common.loading}</PanelEmpty>
          ) : isEmpty ? (
            <PanelEmpty className="py-6">
              <p className="text-foreground font-medium">{kb.codeTableEmpty}</p>
              <button
                type="button"
                className="text-primary mt-3 text-sm font-medium hover:underline"
                onClick={() => setCreateOpen(true)}
              >
                {ct.createEntry}
              </button>
            </PanelEmpty>
          ) : filteredTags.length === 0 ? (
            <InlineEmpty className="p-3">{kb.codeTableSearchEmpty}</InlineEmpty>
          ) : (
            <KnowledgeCatalogSections
              scope={displayScope}
              kb={kb}
              onEditIndustryTag={setEditing}
              onDeleteIndustryTag={setTagToDelete}
              industryTagActionsBusy={deleteBusy || editBusy}
            />
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
        entry={editing ? industryTagToEntry(editing) : null}
        busy={editBusy}
        deleteBusy={deleteBusy}
        attrFields={entryAttrFields}
        onConfirm={onSaveEntry}
        onDelete={async () => {
          if (editing) await removeIndustryTag(editing);
        }}
      />

      <ConfirmDialog
        open={tagToDelete != null}
        onOpenChange={(open) => {
          if (!open) setTagToDelete(null);
        }}
        title={t.common.delete}
        description={ct.deleteEntryConfirm}
        confirmLabel={deleteBusy ? t.common.loading : t.common.delete}
        confirmPending={deleteBusy}
        confirmVariant="destructive"
        onConfirm={() => {
          if (tagToDelete) void removeIndustryTag(tagToDelete);
        }}
        onCancel={() => setTagToDelete(null)}
      />
    </>
  );
}
