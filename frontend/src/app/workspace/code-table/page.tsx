"use client";

import { BookOpenIcon, SettingsIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
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
import { CodeTableDomainEditDialog } from "@/components/workspace/code-table/domain-dialog";
import { CodeTableCreateEntryDialog } from "@/components/workspace/code-table/entry-dialog";
import {
  KNOWLEDGE_CODE_TABLE_DOMAIN,
  KNOWLEDGE_DEFAULT_TYPE_KEY,
  deleteCodeTableDomain,
  listCodeTableDomains,
  updateCodeTableDomain,
  codeTableDomainDisplayName,
  groupCodeTableDomainSummaries,
  primaryCodeTableDomainCategory,
  type CodeTableDomainSummary,
} from "@/core/code-table/api";
import { codeTableDomainHref } from "@/core/code-table/routes";
import { useI18n } from "@/core/i18n/hooks";

const DEFAULT_DOMAINS: CodeTableDomainSummary[] = [
  {
    domain: KNOWLEDGE_CODE_TABLE_DOMAIN,
    type_key: KNOWLEDGE_DEFAULT_TYPE_KEY,
    entry_count: 0,
  },
];

export default function CodeTablePage() {
  const { t } = useI18n();
  const ct = t.codeTable;
  const router = useRouter();
  const [items, setItems] = useState<CodeTableDomainSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editBusy, setEditBusy] = useState(false);
  const [domainToEdit, setDomainToEdit] =
    useState<CodeTableDomainSummary | null>(null);
  const [domainToDelete, setDomainToDelete] =
    useState<CodeTableDomainSummary | null>(null);
  const [query, setQuery] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listCodeTableDomains();
      if (res.items.length > 0) {
        setItems(res.items);
      } else {
        setItems(DEFAULT_DOMAINS);
      }
    } catch (e) {
      setItems(DEFAULT_DOMAINS);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const rows = useMemo(
    () =>
      groupCodeTableDomainSummaries(items).map((item) => ({
        ...item,
        href: codeTableDomainHref(item.domain),
        Icon: BookOpenIcon,
        title: codeTableDomainDisplayName(item, ct.domains.knowledge.label),
        category: primaryCodeTableDomainCategory(items, item.domain) ?? item,
      })),
    [ct.domains.knowledge.label, items],
  );

  const q = query.trim().toLowerCase();
  const filteredRows = useMemo(() => {
    if (!q) return rows;
    return rows.filter(({ domain, title, label }) => {
      const displayLabel = label?.trim().toLowerCase() ?? "";
      return (
        domain.toLowerCase().includes(q) ||
        title.toLowerCase().includes(q) ||
        displayLabel.includes(q)
      );
    });
  }, [q, rows]);

  const isEmpty = !loading && rows.length === 0;

  const countLabel = useMemo(() => {
    if (rows.length === 0) return undefined;
    if (q) return ct.countFiltered(filteredRows.length, rows.length);
    return ct.countTotal(rows.length);
  }, [ct, filteredRows.length, q, rows.length]);

  async function onEditDomain(input: {
    type_key: string;
    new_type_key?: string;
    label: string;
  }) {
    if (!domainToEdit) return;
    setEditBusy(true);
    setError(null);
    try {
      await updateCodeTableDomain(domainToEdit.domain, input);
      setEditOpen(false);
      setDomainToEdit(null);
      toast.success(ct.domainUpdated);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditBusy(false);
    }
  }

  async function removeDomain(target: CodeTableDomainSummary) {
    setDeleteBusy(true);
    setError(null);
    try {
      const res = await deleteCodeTableDomain(target.domain);
      setDomainToDelete(null);
      toast.success(ct.domainDeleted(res.deleted));
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setDeleteBusy(false);
    }
  }

  const deleteLabel = domainToDelete
    ? codeTableDomainDisplayName(domainToDelete, ct.domains.knowledge.label)
    : "";

  return (
    <>
      <Shell
        fillBody={isEmpty}
        header={
          <ShellHeader
            title={ct.title}
            description={ct.description}
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
        {error ? (
          <p className="text-destructive px-2 text-sm">{error}</p>
        ) : null}

        <ItemListPanel
          title={ct.listTitle}
          countLabel={countLabel}
          toolbar={
            rows.length > 0 ? (
              <ListPanelToolbar>
                <ListSearchField
                  value={query}
                  onChange={setQuery}
                  placeholder={ct.searchPlaceholder}
                />
              </ListPanelToolbar>
            ) : undefined
          }
        >
          {loading ? (
            <PanelEmpty className="py-6">{t.common.loading}</PanelEmpty>
          ) : isEmpty ? (
            <PanelEmpty className="py-6">
              <p className="text-foreground font-medium">{ct.empty}</p>
              <button
                type="button"
                className="text-primary mt-3 text-sm font-medium hover:underline"
                onClick={() => setCreateOpen(true)}
              >
                {ct.createEntry}
              </button>
            </PanelEmpty>
          ) : filteredRows.length === 0 ? (
            <InlineEmpty className="p-3">{ct.searchEmpty}</InlineEmpty>
          ) : (
            <ul className={itemListFlushClass}>
              {filteredRows.map(
                ({ domain, entry_count, href, Icon, title, category }) => (
                  <li
                    key={domain}
                    className="hover:bg-muted/40 flex min-w-0 items-center gap-2 px-4 py-2 transition-colors"
                  >
                    <Link
                      href={href}
                      className="flex min-w-0 flex-1 items-center gap-2"
                    >
                      <Icon className="text-muted-foreground size-3.5 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="text-foreground truncate text-sm leading-snug font-medium">
                          {title}
                        </div>
                      </div>
                      <span className="text-muted-foreground shrink-0 text-xs">
                        {ct.entryCount(entry_count)}
                      </span>
                    </Link>
                    <div className="flex shrink-0 items-center gap-1">
                      <CardAction
                        icon={SettingsIcon}
                        label={t.common.edit}
                        onClick={() => {
                          setDomainToEdit(category);
                          setEditOpen(true);
                        }}
                        disabled={deleteBusy}
                      />
                      <CardAction
                        icon={Trash2Icon}
                        label={t.common.delete}
                        onClick={() => setDomainToDelete(category)}
                        disabled={
                          deleteBusy || domain === KNOWLEDGE_CODE_TABLE_DOMAIN
                        }
                      />
                    </div>
                  </li>
                ),
              )}
            </ul>
          )}
        </ItemListPanel>
      </Shell>

      <CodeTableCreateEntryDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onError={(e) => setError(e.message)}
        scope={{
          onCreated: async (createdDomain) => {
            await reload();
            router.push(codeTableDomainHref(createdDomain));
          },
        }}
      />

      <CodeTableDomainEditDialog
        open={editOpen}
        onOpenChange={(open) => {
          setEditOpen(open);
          if (!open) setDomainToEdit(null);
        }}
        target={domainToEdit}
        busy={editBusy}
        onConfirm={onEditDomain}
      />

      <ConfirmDialog
        open={domainToDelete != null}
        onOpenChange={(open) => {
          if (!open) setDomainToDelete(null);
        }}
        title={t.common.delete}
        description={ct.deleteDomainConfirm(deleteLabel)}
        confirmLabel={deleteBusy ? t.common.loading : t.common.delete}
        confirmPending={deleteBusy}
        confirmVariant="destructive"
        onConfirm={() => {
          if (domainToDelete) void removeDomain(domainToDelete);
        }}
        onCancel={() => setDomainToDelete(null)}
      />
    </>
  );
}
