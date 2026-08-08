import {
  formatWorkspaceItemTimestamp,
  type FormDialogEditResourceMeta,
} from "@/components/component";
import type { Translations } from "@/core/i18n/locales/types";
import {
  utcToZonedLocalInput,
  zonedLocalToUtcIso,
} from "@/core/scheduled-tasks/cron";

import type { Space } from "./api";
import { roleLabel } from "./labels";

type KnowledgeT = Translations["knowledge"];

export function buildSpaceEditMeta(
  space: Space | null,
  locale: string,
  t: KnowledgeT,
): FormDialogEditResourceMeta | undefined {
  if (!space) return undefined;
  const rows = space.my_role
    ? [
        {
          label: t.roleLabel,
          value: roleLabel(space.my_role, t),
        },
      ]
    : [];
  const raw = space.created_at?.trim();
  const createdAt = raw ? formatWorkspaceItemTimestamp(raw, locale) : undefined;
  if (rows.length === 0 && !createdAt) return undefined;
  return { rows, createdAt };
}

function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** Document is available for retrieval unless attrs.enabled is explicitly false. */
export function readDocumentEnabled(
  attrs?: Record<string, unknown> | null,
): boolean {
  const value = attrs?.enabled;
  if (value === false || value === "false") {
    return false;
  }
  return true;
}

export function effectiveToLocalValue(
  iso: string | null | undefined,
  timezone = browserTimezone(),
): string {
  if (!iso?.trim()) {
    return "";
  }
  return utcToZonedLocalInput(iso, timezone);
}

export function localValueToEffectiveTo(
  local: string,
  timezone = browserTimezone(),
): string | null {
  const trimmed = local.trim();
  if (!trimmed) {
    return null;
  }
  return zonedLocalToUtcIso(trimmed, timezone);
}

export type DocumentEffectiveStatus = "valid" | "expired" | "pending";

function parseEffectiveInstant(iso: string | null | undefined): Date | null {
  if (!iso?.trim()) return null;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function documentEffectiveStatus(
  doc: {
    effective_from?: string | null;
    effective_to?: string | null;
  },
  asOf: Date = new Date(),
): DocumentEffectiveStatus {
  const start = parseEffectiveInstant(doc.effective_from);
  const end = parseEffectiveInstant(doc.effective_to);
  if (start && asOf < start) return "pending";
  if (end && asOf > end) return "expired";
  return "valid";
}
