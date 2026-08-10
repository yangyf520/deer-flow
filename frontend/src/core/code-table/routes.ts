export function codeTableDomainHref(domain: string): string {
  const normalized = domain.trim().toLowerCase();
  return `/workspace/code-table/${encodeURIComponent(normalized)}`;
}
