"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

/** Legacy route — knowledge tag management lives under `/workspace/code-table/knowledge`. */
export default function KnowledgeScenariosRedirectPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const qs = searchParams.toString();
    router.replace(
      qs
        ? `/workspace/code-table/knowledge?${qs}`
        : "/workspace/code-table/knowledge",
    );
  }, [router, searchParams]);

  return null;
}
