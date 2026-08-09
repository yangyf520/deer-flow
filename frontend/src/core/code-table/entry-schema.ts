import type { CodeTableTranslations } from "@/core/i18n/locales/code-table";
import type { KnowledgeIndustryTag } from "@/core/knowledge/api";

export type CodeTableEntryRecord = {
  code: string;
  label: string;
  attrs: Record<string, unknown>;
};

export type CodeTableEntryFormValues = {
  code: string;
  label: string;
  attrs: Record<string, string[]>;
};

export type CodeTableAttrFieldSpec = {
  attrKey: string;
  label: string;
  placeholder?: string;
  hint?: string;
  rows?: number;
};

export function parseListField(text: string): string[] {
  return text
    .split(/[,，\n]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function formatListField(items?: string[]): string {
  return (items ?? []).join("\n");
}

export function readStringListAttr(
  attrs: Record<string, unknown> | undefined,
  key: string,
): string[] {
  const raw = attrs?.[key];
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => String(item).trim()).filter(Boolean);
}

function readStringAttr(
  attrs: Record<string, unknown> | undefined,
  key: string,
): string {
  const raw = attrs?.[key];
  return typeof raw === "string" ? raw.trim() : "";
}

export function industryTagAttrFields(
  ct: CodeTableTranslations,
): CodeTableAttrFieldSpec[] {
  return [
    {
      attrKey: "keywords",
      label: ct.attrFields.keywords.label,
      placeholder: ct.attrFields.keywords.placeholder,
      hint: ct.attrFields.keywords.hint,
      rows: 3,
    },
    {
      attrKey: "department",
      label: ct.attrFields.department.label,
      placeholder: ct.attrFields.department.placeholder,
      hint: ct.attrFields.department.hint,
      rows: 2,
    },
    {
      attrKey: "aliases",
      label: ct.attrFields.aliases.label,
      placeholder: ct.attrFields.aliases.placeholder,
      hint: ct.attrFields.aliases.hint,
      rows: 2,
    },
  ];
}

export function industryTagToEntry(
  tag: KnowledgeIndustryTag,
): CodeTableEntryRecord {
  return {
    code: tag.id,
    label: tag.label?.trim() ?? tag.id,
    attrs: {
      keywords: tag.keywords ?? [],
      department: tag.department ?? [],
      aliases: tag.aliases ?? [],
      space_id: tag.space_id ?? "",
    },
  };
}

export function flatEntryToEntry(entry: {
  code: string;
  label: string;
  attrs?: Record<string, unknown>;
}): CodeTableEntryRecord {
  return {
    code: entry.code,
    label: entry.label?.trim() ?? entry.code,
    attrs: entry.attrs ?? {},
  };
}

export function flatEntryToIndustryTag(entry: {
  code: string;
  label: string;
  attrs?: Record<string, unknown>;
}): KnowledgeIndustryTag {
  return {
    id: entry.code,
    label: entry.label?.trim() ?? entry.code,
    keywords: readStringListAttr(entry.attrs, "keywords"),
    department: readStringListAttr(entry.attrs, "department"),
    aliases: readStringListAttr(entry.attrs, "aliases"),
    space_id: readStringAttr(entry.attrs, "space_id"),
  };
}

export function formValuesFromEntry(
  entry: CodeTableEntryRecord,
  attrFields: CodeTableAttrFieldSpec[],
): Omit<CodeTableEntryFormValues, "code"> & { code: string } {
  const attrs: Record<string, string[]> = {};
  for (const field of attrFields) {
    attrs[field.attrKey] = readStringListAttr(entry.attrs, field.attrKey);
  }
  return {
    code: entry.code,
    label: entry.label,
    attrs,
  };
}

export function attrsFromFormValues(
  values: CodeTableEntryFormValues,
  attrFields: CodeTableAttrFieldSpec[],
): Record<string, string[]> {
  const attrs: Record<string, string[]> = {};
  for (const field of attrFields) {
    attrs[field.attrKey] = values.attrs[field.attrKey] ?? [];
  }
  return attrs;
}
