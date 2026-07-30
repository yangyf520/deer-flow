export type ApiKeysTranslations = {
  title: string;
  description: string;
  listTitle: string;
  countTotal: (count: number) => string;
  countFiltered: (shown: number, total: number) => string;
  searchPlaceholder: string;
  searchEmpty: string;
  emptyTitle: string;
  emptyDescription: string;
  createButton: string;
  creating: string;
  createError: string;
  createdTitle: string;
  createdHint: string;
  copyButton: string;
  editButton: string;
  editTitle: string;
  saveButton: string;
  updating: string;
  updateSuccess: string;
  updateError: string;
  revokeButton: string;
  revoking: string;
  revokeSuccess: string;
  revokeError: string;
  deleteTitle: string;
  deleteDescription: string;
  loadError: string;
  fieldName: string;
  namePlaceholder: string;
  fieldDescription: string;
  descriptionPlaceholder: string;
  fieldAgent: string;
  agentPlaceholder: string;
  noAgentBinding: string;
  leadAgent: string;
  unboundAgent: string;
};

export const apiKeysEnUS: ApiKeysTranslations = {
  title: "API keys",
  description: "Create and manage API keys for programmatic access",
  listTitle: "All keys",
  countTotal: (count) => (count === 1 ? "1 key" : `${count} keys`),
  countFiltered: (shown, total) => `${shown} / ${total}`,
  searchPlaceholder: "Search keys…",
  searchEmpty: "No keys match your search.",
  emptyTitle: "No API keys yet",
  emptyDescription:
    "Create a key to access DeerFlow from scripts or integrations.",
  createButton: "New key",
  creating: "Creating…",
  createError: "Failed to create API key",
  createdTitle: "API key created",
  createdHint: "Copy this key now — it will not be shown again.",
  copyButton: "Copy",
  editButton: "Edit",
  editTitle: "Edit API key",
  saveButton: "Save",
  updating: "Saving…",
  updateSuccess: "API key updated",
  updateError: "Failed to update API key",
  revokeButton: "Revoke",
  revoking: "Revoking…",
  revokeSuccess: "API key revoked",
  revokeError: "Failed to revoke API key",
  deleteTitle: "Revoke API key",
  deleteDescription:
    "This key will stop working immediately. This action cannot be undone.",
  loadError: "Failed to load API keys",
  fieldName: "Name",
  namePlaceholder: "e.g. CI pipeline",
  fieldDescription: "Description",
  descriptionPlaceholder: "What this key is used for",
  fieldAgent: "Agent binding",
  agentPlaceholder: "Select agent",
  noAgentBinding: "No agent binding",
  leadAgent: "Lead agent",
  unboundAgent: "Unbound",
};

export const apiKeysZhCN: ApiKeysTranslations = {
  title: "API 密钥",
  description: "创建和管理用于程序化访问的 API 密钥",
  listTitle: "全部密钥",
  countTotal: (count) => `${count} 个密钥`,
  countFiltered: (shown, total) => `${shown} / ${total}`,
  searchPlaceholder: "搜索密钥…",
  searchEmpty: "没有匹配的密钥。",
  emptyTitle: "还没有 API 密钥",
  emptyDescription: "创建密钥以便脚本或集成访问 DeerFlow。",
  createButton: "新建密钥",
  creating: "创建中…",
  createError: "创建 API 密钥失败",
  createdTitle: "API 密钥已创建",
  createdHint: "请立即复制此密钥 — 之后将无法再次查看。",
  copyButton: "复制",
  editButton: "编辑",
  editTitle: "编辑 API 密钥",
  saveButton: "保存",
  updating: "保存中…",
  updateSuccess: "API 密钥已更新",
  updateError: "更新 API 密钥失败",
  revokeButton: "吊销",
  revoking: "吊销中…",
  revokeSuccess: "API 密钥已吊销",
  revokeError: "吊销 API 密钥失败",
  deleteTitle: "吊销 API 密钥",
  deleteDescription: "此密钥将立即失效，且无法撤销。",
  loadError: "加载 API 密钥失败",
  fieldName: "名称",
  namePlaceholder: "例如：CI 流水线",
  fieldDescription: "描述",
  descriptionPlaceholder: "此密钥的用途",
  fieldAgent: "绑定智能体",
  agentPlaceholder: "选择智能体",
  noAgentBinding: "不绑定智能体",
  leadAgent: "主智能体",
  unboundAgent: "未绑定",
};
