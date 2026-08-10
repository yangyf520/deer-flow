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
import { headerPairedActionButtonClass } from "@/components/component/styles";
import {
  CodeTableEntryCreateDialog,
  CodeTableEntryEditDialog,
} from "@/components/workspace/code-table/entry-dialog";
import {
  createCodeTableEntry,
  deleteCodeTableEntry,
  listCodeTableDomains,
  loadCodeTableBundle,
  normalizeCodeTableFlatBundle,
  updateCodeTableEntry,
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

const INDUSTRY_TYPE_KEY = "industry_tag";

type EntryDisplayRow = {
  key: string;
  label: string;
  code: string;
  subtitle?: string;
  searchText: string;
  record: CodeTableEntryRecord;
};

function entryMatchesQuery(row: EntryDisplayRow, q: string): boolean {
  return row.searchText.toLowerCase().includes(q);
}

export function FlatCodeTablePanel({
  domain,
  backHref,
}: {
  domain: string;
  backHref?: string;
}) {
  const { t, locale } = useI18n();
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
  const [entryCodeToDelete, setEntryCodeToDelete] = useState<string | null>(
    null,
  );

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
      const flat = normalizeCodeTableFlatBundle(
        domain,
        bundle,
        resolvedTypeKey,
      );
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

  const displayRows = useMemo((): EntryDisplayRow[] => {
    if (typeKey === INDUSTRY_TYPE_KEY) {
      return entries.map((entry) => {
        const tag = flatEntryToIndustryTag(entry);
        const label = tag.label?.trim() ?? tag.id;
        const keywords = tag.keywords ?? [];
        const department = tag.department ?? [];
        const subtitle = keywords.length > 0 ? keywords.join(" · ") : undefined;
        return {
          key: tag.id,
          label,
          code: tag.id,
          subtitle,
          searchText: [label, tag.id, ...keywords, ...department].join(" "),
          record: industryTagToEntry(tag),
        };
      });
    }
    return entries.map((entry) => {
      const record = flatEntryToEntry(entry);
      return {
        key: record.code,
        label: record.label,
        code: record.code,
        searchText: `${record.label} ${record.code}`,
        record,
      };
    });
  }, [entries, typeKey]);

  const q = query.trim().toLowerCase();
  const filteredRows = useMemo(() => {
    if (!q) return displayRows;
    return displayRows.filter((row) => entryMatchesQuery(row, q));
  }, [displayRows, q]);

  const isEmpty = !loading && entries.length === 0;
  const countLabel =
    entries.length > 0
      ? q
        ? ct.countFiltered(filteredRows.length, entries.length)
        : ct.entryCount(entries.length)
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
      setEntryCodeToDelete(null);
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
          title={ct.entriesListTitle}
          countLabel={countLabel}
          toolbar={
            entries.length > 0 ? (
              <ListPanelToolbar>
                <ListSearchField
                  value={query}
                  onChange={setQuery}
                  placeholder={ct.entriesSearchPlaceholder}
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
          ) : filteredRows.length === 0 ? (
            <InlineEmpty className="p-3">{ct.entriesSearchEmpty}</InlineEmpty>
          ) : (
            <ul className="divide-border divide-y">
              {filteredRows.map((row) => (
                <li
                  key={row.key}
                  className="hover:bg-muted/40 flex min-w-0 items-center gap-2 px-4 py-2 transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-foreground truncate text-sm font-medium">
                      {row.label}
                      {row.code !== row.label ? (
                        <span className="text-muted-foreground ml-2 font-mono text-xs font-normal">
                          {row.code}
                        </span>
                      ) : null}
                    </div>
                    {row.subtitle ? (
                      <div className="text-muted-foreground mt-0.5 truncate text-xs">
                        {row.subtitle}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <CardAction
                      icon={SettingsIcon}
                      label={t.common.edit}
                      onClick={() => setEditing(row.record)}
                      disabled={deleteBusy || editBusy}
                    />
                    <CardAction
                      icon={Trash2Icon}
                      label={t.common.delete}
                      onClick={() => setEntryCodeToDelete(row.code)}
                      disabled={deleteBusy || editBusy}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </ItemListPanel>
      </Shell>

      <CodeTableEntryCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        busy={createBusy}
        attrFields={entryAttrFields}
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
        open={entryCodeToDelete != null}
        onOpenChange={(open) => {
          if (!open) setEntryCodeToDelete(null);
        }}
        title={t.common.delete}
        description={ct.deleteEntryConfirm}
        confirmLabel={deleteBusy ? t.common.loading : t.common.delete}
        confirmPending={deleteBusy}
        confirmVariant="destructive"
        onConfirm={() => {
          if (entryCodeToDelete) void removeEntry(entryCodeToDelete);
        }}
        onCancel={() => setEntryCodeToDelete(null)}
      />
    </>
  );
}
