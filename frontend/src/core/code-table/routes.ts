/** Tag-management entry for the knowledge code-table domain. */
export function knowledgeTagManagementHref(): string {
  return "/workspace/code-table/knowledge";
}

export function codeTableDomainHref(domain: string): string {
  const normalized = domain.trim().toLowerCase();
  if (normalized !== "knowledge") {
    return `/workspace/code-table/${encodeURIComponent(normalized)}`;
  }
  return knowledgeTagManagementHref();
}
