import {
  formatWorkspaceItemTimestamp,
  type FormDialogEditResourceMeta,
} from "@/components/component";
import type { Translations } from "@/core/i18n/locales/types";

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
