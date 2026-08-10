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
  itemListFlushClass,
  ListPanelToolbar,
  ListSearchField,
  PanelEmpty,
  Shell,
  ShellHeader,
} from "@/components/component";
import { headerPairedActionButtonClass } from "@/components/component/styles";
import {
  CodeTableCreateEntryDialog,
  CodeTableEntryEditDialog,
} from "@/components/workspace/code-table/entry-dialog";
import {
  DEFAULT_CODE_TABLE_TYPE_KEY,
  deleteCodeTableEntry,
  listCodeTableDomains,
  loadCodeTableBundle,
  normalizeCodeTableFlatBundle,
  updateCodeTableEntry,
  codeTableDomainDisplayName,
  isCodeTableUserEntry,
  primaryCodeTableDomainCategory,
  type CodeTableFlatEntry,
} from "@/core/code-table/api";
import {
  attrsFromFormValues,
  codeTableEntryAttrFields,
  flatEntryToEntry,
  readStringListAttr,
  type CodeTableEntryFormValues,
  type CodeTableEntryRecord,
} from "@/core/code-table/entry-schema";
import { useI18n } from "@/core/i18n/hooks";

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

function isFlatDomainList(
  items: readonly { parent_code?: string }[],
  summaryParentCode: string,
): boolean {
  if (summaryParentCode) return false;
  return !items.some((entry) => (entry.parent_code ?? "").trim());
}

/** Child entries for a domain; flat domains list all rows, others list children only. */
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
  const [parentCode, setParentCode] = useState("");
  const [flatList, setFlatList] = useState(true);
  const [title, setTitle] = useState("");
  const [entries, setEntries] = useState<CodeTableFlatEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<CodeTableEntryRecord | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [entryCodeToDelete, setEntryCodeToDelete] = useState<string | null>(
    null,
  );

  const entryAttrFields = useMemo(() => codeTableEntryAttrFields(ct), [ct]);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [domainsRes, bundle] = await Promise.all([
        listCodeTableDomains(),
        loadCodeTableBundle(domain),
      ]);
      const category = primaryCodeTableDomainCategory(domainsRes.items, domain);
      const flat = normalizeCodeTableFlatBundle(
        domain,
        bundle,
        category?.type_key ?? DEFAULT_CODE_TABLE_TYPE_KEY,
      );
      const items = flat.items.filter(isCodeTableUserEntry);
      const rootEntries = items.filter(
        (entry) => !(entry.parent_code ?? "").trim(),
      );
      const categoryTypeKey = category?.type_key?.trim();
      const rootTypeKey = rootEntries[0]?.type_key?.trim();
      const resolvedTypeKey =
        [categoryTypeKey, rootTypeKey].find((key) => Boolean(key?.length)) ??
        DEFAULT_CODE_TABLE_TYPE_KEY;
      const summaryParentCode = category?.parent_code?.trim() ?? "";
      const isFlatList = isFlatDomainList(items, summaryParentCode);
      const resolvedParentCode = isFlatList
        ? ""
        : summaryParentCode.length > 0
          ? summaryParentCode
          : (rootEntries[0]?.code ?? "");
      setTypeKey(resolvedTypeKey);
      setParentCode(resolvedParentCode);
      setFlatList(isFlatList);
      setTitle(
        category
          ? codeTableDomainDisplayName(category, ct.domains.knowledge.label)
          : domain,
      );
      setEntries(
        isFlatList
          ? items
          : resolvedParentCode
            ? items.filter(
                (entry) =>
                  (entry.parent_code ?? "").trim() === resolvedParentCode,
              )
            : rootEntries,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [ct.domains.knowledge.label, domain]);

  useEffect(() => {
    void reload();
  }, [reload, locale]);

  const displayRows = useMemo((): EntryDisplayRow[] => {
    return entries.map((entry) => {
      const record = flatEntryToEntry(entry);
      const keywords = readStringListAttr(record.attrs, "keywords");
      const department = readStringListAttr(record.attrs, "department");
      const aliases = readStringListAttr(record.attrs, "aliases");
      const subtitle = keywords.length > 0 ? keywords.join(" · ") : undefined;
      return {
        key: record.code,
        label: record.label,
        code: record.code,
        subtitle,
        searchText: [
          record.label,
          record.code,
          ...keywords,
          ...department,
          ...aliases,
        ].join(" "),
        record,
      };
    });
  }, [entries]);

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

  const createTypeKey =
    typeKey.length > 0 ? typeKey : DEFAULT_CODE_TABLE_TYPE_KEY;

  const canCreate =
    !loading && Boolean(createTypeKey) && (flatList || parentCode.length > 0);

  async function onSaveEntry(input: Omit<CodeTableEntryFormValues, "code">) {
    if (!editing || !typeKey) return;
    setEditBusy(true);
    setError(null);
    try {
      await updateCodeTableEntry(domain, editing.code, {
        type_key: typeKey,
        label: input.label,
        parent_code: flatList ? "" : parentCode,
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
      await deleteCodeTableEntry(
        domain,
        code,
        typeKey,
        flatList ? "" : parentCode,
      );
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
            title={title}
            description={ct.description}
            descriptionSuffix={domain}
            actions={
              <HeaderCreateButton
                className={headerPairedActionButtonClass}
                onClick={() => setCreateOpen(true)}
                disabled={!canCreate}
              >
                {ct.createEntry}
              </HeaderCreateButton>
            }
          />
        }
      >
        {error ? <AlertError>{error}</AlertError> : null}

        <ItemListPanel
          title={ct.listTitle}
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
                disabled={!canCreate}
              >
                {ct.createEntry}
              </button>
            </PanelEmpty>
          ) : filteredRows.length === 0 ? (
            <InlineEmpty className="p-3">{ct.entriesSearchEmpty}</InlineEmpty>
          ) : (
            <ul className={itemListFlushClass}>
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

      <CodeTableCreateEntryDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (open) setError(null);
        }}
        onError={(e) => setError(e.message)}
        scope={{
          domain,
          typeKey: createTypeKey,
          parentCode: flatList ? "" : parentCode,
          attrFields: entryAttrFields,
          onCreated: () => reload(),
        }}
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
