"use client";

import { SaveIcon, Trash2Icon } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { PageShell } from "@/app/workspace/knowledge/ui";
import { AlertError, Header, InlineEmpty } from "@/components/component";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import {
  deleteGrant,
  getSpace,
  listGrants,
  roleLabel,
  SPACE_ROLE_VALUES,
  type SpaceGrant,
  type SpaceRoleValue,
  upsertGrant,
} from "@/core/knowledge";

export default function KnowledgeGrantsPage() {
  const { t } = useI18n();
  const params = useParams<{ spaceId: string }>();
  const spaceId = decodeURIComponent(params.spaceId);
  const [grants, setGrants] = useState<SpaceGrant[]>([]);
  const [subjectType, setSubjectType] = useState<"user" | "dept">("user");
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState<SpaceRoleValue>("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [grantToDelete, setGrantToDelete] = useState<SpaceGrant | null>(null);

  const reload = useCallback(async () => {
    try {
      const space = await getSpace(spaceId);
      if (space.my_role !== "admin") {
        setGrants([]);
        return;
      }
      const response = await listGrants(spaceId);
      setGrants(response.items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [spaceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function saveGrant() {
    if (!subject.trim()) return;
    setBusy(true);
    try {
      await upsertGrant(spaceId, {
        subject_type: subjectType,
        subject_id: subject.trim(),
        role,
      });
      setSubject("");
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function removeGrant(grant: SpaceGrant) {
    setBusy(true);
    try {
      await deleteGrant(spaceId, grant.subject_type, grant.subject_id);
      setGrantToDelete(null);
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell maxWidth="4xl">
      <Header
        backHref="/workspace/knowledge"
        title={t.knowledge.grantsTitle}
        description={t.knowledge.grantsSpace.replace("{id}", spaceId)}
      />

      <AlertError>{error}</AlertError>

      <section className="bg-card rounded-xl border p-4">
        <h2 className="mb-3 text-sm font-medium">{t.knowledge.addGrant}</h2>
        <p className="text-muted-foreground mb-3 text-xs">
          {t.knowledge.grantsUpstreamHint}
        </p>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
          <Select
            value={subjectType}
            onValueChange={(value) => {
              setSubjectType(value as "user" | "dept");
              setSubject("");
            }}
          >
            <SelectTrigger className="sm:w-36">
              <SelectValue placeholder={t.knowledge.subjectType} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="user">{t.knowledge.user}</SelectItem>
              <SelectItem value="dept">{t.knowledge.dept}</SelectItem>
            </SelectContent>
          </Select>
          <Input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder={
              subjectType === "dept"
                ? t.knowledge.deptPlaceholder
                : t.knowledge.userPlaceholder
            }
            className="min-w-0 flex-1"
          />
          <Select
            value={role}
            onValueChange={(value) => setRole(value as SpaceRoleValue)}
          >
            <SelectTrigger className="sm:w-40">
              <SelectValue placeholder={t.knowledge.roleLabel} />
            </SelectTrigger>
            <SelectContent>
              {SPACE_ROLE_VALUES.map((value) => (
                <SelectItem key={value} value={value}>
                  {roleLabel(value, t.knowledge)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            disabled={busy || !subject.trim()}
            onClick={() => void saveGrant()}
          >
            <SaveIcon />
            {t.knowledge.upsertGrant}
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t.knowledge.currentGrants}</h2>
        {grants.length === 0 ? (
          <InlineEmpty className="p-6">{t.knowledge.emptyGrants}</InlineEmpty>
        ) : (
          <ul className="divide-border bg-card divide-y rounded-xl border">
            {grants.map((grant) => (
              <li key={grant.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-sm">
                    {grant.subject_id}
                  </p>
                  <p className="text-muted-foreground truncate text-xs">
                    {grant.subject_type}
                  </p>
                </div>
                <Badge variant="outline" className="text-xs">
                  {grant.subject_type === "dept"
                    ? t.knowledge.dept
                    : t.knowledge.user}
                </Badge>
                <Badge variant="secondary">
                  {roleLabel(grant.role, t.knowledge)}
                </Badge>
                <Tooltip content={t.knowledge.deleteGrantTooltip}>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    disabled={busy}
                    onClick={() => setGrantToDelete(grant)}
                  >
                    <Trash2Icon />
                    <span className="sr-only">{t.common.delete}</span>
                  </Button>
                </Tooltip>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Dialog
        open={grantToDelete != null}
        onOpenChange={(open) => {
          if (!open) setGrantToDelete(null);
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t.common.delete}</DialogTitle>
            <DialogDescription>{t.common.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setGrantToDelete(null)}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={busy}
              onClick={() => {
                if (grantToDelete) void removeGrant(grantToDelete);
              }}
            >
              {busy ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}
