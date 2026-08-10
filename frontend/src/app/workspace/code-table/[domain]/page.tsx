"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { FlatCodeTablePanel } from "@/components/workspace/code-table/flat-entries-panel";

export default function CodeTableDomainPage() {
  const params = useParams<{ domain: string }>();
  const router = useRouter();
  const domain = decodeURIComponent(params.domain ?? "")
    .trim()
    .toLowerCase();

  useEffect(() => {
    if (!domain) {
      router.replace("/workspace/code-table");
    }
  }, [domain, router]);

  if (!domain) return null;

  return (
    <FlatCodeTablePanel domain={domain} backHref="/workspace/code-table" />
  );
}
