"use client";

import { SettingsIcon, Trash2Icon } from "lucide-react";
import type { ReactNode } from "react";

import { CardAction } from "@/components/component";
import { workspacePageInsetXClass } from "@/components/component/styles";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeTranslations } from "@/core/i18n/locales/knowledge";
import type { KnowledgeIndustryTag } from "@/core/knowledge/api";
import type { CatalogScope } from "@/core/knowledge/catalog-scope";
import { tagGroupLabel, tagLabel } from "@/core/knowledge/labels";
import { cn } from "@/lib/utils";

function Section({
  title,
  empty,
  children,
}: {
  title?: string;
  empty?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      {title ? (
        <h2 className="text-foreground text-sm font-medium">{title}</h2>
      ) : null}
      {children}
      {empty ? <p className="text-muted-foreground text-sm">{empty}</p> : null}
    </section>
  );
}

export function KnowledgeCatalogSections({
  scope,
  kb,
  className,
  showDocumentCatalog = false,
  onEditIndustryTag,
  onDeleteIndustryTag,
  industryTagActionsBusy = false,
}: {
  scope: CatalogScope;
  kb: KnowledgeTranslations;
  className?: string;
  /** Document kind/tag/group rows — hidden on industry tag management by default. */
  showDocumentCatalog?: boolean;
  onEditIndustryTag?: (tag: KnowledgeIndustryTag) => void;
  onDeleteIndustryTag?: (tag: KnowledgeIndustryTag) => void;
  industryTagActionsBusy?: boolean;
}) {
  const { t } = useI18n();
  const showIndustryTagActions =
    onEditIndustryTag != null || onDeleteIndustryTag != null;

  return (
    <div
      className={cn(
        workspacePageInsetXClass,
        "flex flex-col gap-3 py-1.5 pb-2",
        className,
      )}
    >
      <Section
        empty={
          (scope.industry_tags?.length ?? 0) === 0
            ? kb.codeTableIndustryTagsEmpty
            : undefined
        }
      >
        {(scope.industry_tags?.length ?? 0) > 0 ? (
          <ul className="flex flex-col gap-2">
            {(scope.industry_tags ?? []).map((item) => (
              <li
                key={item.id}
                className="border-border/60 bg-muted/20 rounded-lg border px-3 py-2"
              >
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-foreground text-sm font-medium">
                      {item.label?.trim() ?? item.id}
                      <span className="text-muted-foreground ml-2 font-mono text-xs">
                        {item.id}
                      </span>
                    </div>
                    {item.keywords && item.keywords.length > 0 ? (
                      <div className="text-muted-foreground mt-1 text-xs">
                        {item.keywords.join(" · ")}
                      </div>
                    ) : null}
                  </div>
                  {showIndustryTagActions ? (
                    <div className="flex shrink-0 items-center gap-1">
                      {onEditIndustryTag ? (
                        <CardAction
                          icon={SettingsIcon}
                          label={t.common.edit}
                          onClick={() => onEditIndustryTag(item)}
                          disabled={industryTagActionsBusy}
                        />
                      ) : null}
                      {onDeleteIndustryTag ? (
                        <CardAction
                          icon={Trash2Icon}
                          label={t.common.delete}
                          onClick={() => onDeleteIndustryTag(item)}
                          disabled={industryTagActionsBusy}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </Section>

      {showDocumentCatalog ? (
        <>
          <Section
            title={kb.codeTableTags}
            empty={scope.tags.length === 0 ? kb.codeTableTagsEmpty : undefined}
          >
            {scope.tags.length > 0 ? (
              <ul className="flex flex-wrap gap-2">
                {scope.tags.map((tag) => (
                  <li key={`${tag.scenario ?? ""}:${tag.id}`}>
                    <Badge variant="secondary" className="font-normal">
                      {tag.label?.trim() ?? tagLabel(tag.id, kb)}
                      <span className="text-muted-foreground ml-1.5 font-mono text-[10px]">
                        {tag.id}
                      </span>
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : null}
          </Section>

          <Section
            title={kb.codeTableKinds}
            empty={
              scope.kinds.length === 0 ? kb.codeTableKindsEmpty : undefined
            }
          >
            {scope.kinds.length > 0 ? (
              <ul className="flex flex-wrap gap-2">
                {scope.kinds.map((kind) => (
                  <li key={kind.id}>
                    <Badge variant="outline" className="font-normal">
                      {kind.label?.trim() ?? kind.id}
                      <span className="text-muted-foreground ml-1.5 font-mono text-[10px]">
                        {kind.id}
                      </span>
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : null}
          </Section>

          <Section
            title={kb.codeTableTagGroups}
            empty={
              scope.tag_groups.length === 0
                ? kb.codeTableTagGroupsEmpty
                : undefined
            }
          >
            {scope.tag_groups.length > 0 ? (
              <ul className="flex flex-col gap-2">
                {scope.tag_groups.map((group) => (
                  <li
                    key={`${group.scenario ?? ""}:${group.id}`}
                    className="border-border/60 bg-muted/20 rounded-lg border px-3 py-2"
                  >
                    <div className="text-foreground text-sm font-medium">
                      {tagGroupLabel(group.id, kb, group)}
                    </div>
                    <div className="text-muted-foreground mt-1 font-mono text-xs">
                      {group.tags.join(", ")}
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}
          </Section>
        </>
      ) : null}
    </div>
  );
}
