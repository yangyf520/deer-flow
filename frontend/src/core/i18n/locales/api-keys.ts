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
  sectionBasic: string;
  saveButton: string;
  updating: string;
  updateSuccess: string;
  updateError: string;
  disableButton: string;
  disabling: string;
  disableSuccess: string;
  disableError: string;
  disableTitle: string;
  disableDescription: string;
  enableButton: string;
  enabling: string;
  enableSuccess: string;
  enableError: string;
  deleteButton: string;
  deleting: string;
  deleteSuccess: string;
  deleteError: string;
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
  sectionBasic: "Basics",
  saveButton: "Save",
  updating: "Saving…",
  updateSuccess: "API key updated",
  updateError: "Failed to update API key",
  disableButton: "Disable",
  disabling: "Disabling…",
  disableSuccess: "API key disabled",
  disableError: "Failed to disable API key",
  disableTitle: "Disable API key",
  disableDescription:
    "This key will stop working immediately. You can re-enable it later.",
  enableButton: "Enable",
  enabling: "Enabling…",
  enableSuccess: "API key enabled",
  enableError: "Failed to enable API key",
  deleteButton: "Delete",
  deleting: "Deleting…",
  deleteSuccess: "API key deleted",
  deleteError: "Failed to delete API key",
  deleteTitle: "Delete API key",
  deleteDescription:
    "This permanently removes the key record. This action cannot be undone.",
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
  sectionBasic: "基本信息",
  saveButton: "保存",
  updating: "保存中…",
  updateSuccess: "API 密钥已更新",
  updateError: "更新 API 密钥失败",
  disableButton: "禁用",
  disabling: "禁用中…",
  disableSuccess: "API 密钥已禁用",
  disableError: "禁用 API 密钥失败",
  disableTitle: "禁用 API 密钥",
  disableDescription: "此密钥将立即失效，之后可以重新启用。",
  enableButton: "启用",
  enabling: "启用中…",
  enableSuccess: "API 密钥已启用",
  enableError: "启用 API 密钥失败",
  deleteButton: "删除",
  deleting: "删除中…",
  deleteSuccess: "API 密钥已删除",
  deleteError: "删除 API 密钥失败",
  deleteTitle: "删除 API 密钥",
  deleteDescription: "将永久删除此密钥记录，且无法恢复。",
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
