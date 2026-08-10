export type CodeTableTranslations = {
  title: string;
  description: string;
  listTitle: string;
  entriesListTitle: string;
  empty: string;
  searchPlaceholder: string;
  searchEmpty: string;
  entriesSearchPlaceholder: string;
  entriesSearchEmpty: string;
  countTotal: (count: number) => string;
  countFiltered: (shown: number, total: number) => string;
  openDomain: string;
  entryCount: (count: number) => string;
  deleteDomainConfirm: (label: string) => string;
  domainDeleted: (count: number) => string;
  createDomain: string;
  editDomain: string;
  domainCreated: string;
  domainUpdated: string;
  domainField: string;
  domainFieldHint: string;
  domainFieldPlaceholder: string;
  typeKeyField: string;
  typeKeyFieldHint: string;
  typeKeyFieldPlaceholder: string;
  domainLabelField: string;
  domainLabelPlaceholder: string;
  domainFieldReadonlyHint: string;
  typeKeyReadonlyHint: string;
  typeKeyInUseHint: string;
  entriesEmpty: string;
  createEntry: string;
  editEntry: string;
  sectionBasic: string;
  sectionAttrs: string;
  entryCode: string;
  entryLabel: string;
  entryCodePlaceholder: string;
  entryLabelPlaceholder: string;
  entryCodeHint: string;
  deleteEntryConfirm: string;
  entryCreated: string;
  entryUpdated: string;
  entryDeleted: string;
  attrFields: {
    keywords: { label: string; placeholder: string; hint: string };
    department: { label: string; placeholder: string; hint: string };
    aliases: { label: string; placeholder: string; hint: string };
  };
  domains: {
    knowledge: {
      label: string;
      description: string;
    };
  };
};

export const codeTableEnUS: CodeTableTranslations = {
  title: "Code tables",
  description:
    "Manage shared code lists by domain for tags, categories, and lookups.",
  listTitle: "Code table list",
  entriesListTitle: "Code table list",
  empty: "No code-table domains are registered yet.",
  searchPlaceholder: "Search domains…",
  searchEmpty: "No matching domains.",
  entriesSearchPlaceholder: "Search entries…",
  entriesSearchEmpty: "No matching entries.",
  countTotal: (count) => `${count} entries`,
  countFiltered: (shown, total) => `${shown} / ${total}`,
  openDomain: "Manage",
  entryCount: (count) => `${count} entries`,
  deleteDomainConfirm: (label) =>
    `Delete all entries in “${label}”? This removes the entire code-table category and cannot be undone.`,
  domainDeleted: (count) =>
    count === 1
      ? "Deleted 1 code-table entry"
      : `Deleted ${count} code-table entries`,
  createDomain: "New domain",
  editDomain: "Edit domain",
  domainCreated: "Domain created",
  domainUpdated: "Domain updated",
  domainField: "Domain",
  domainFieldHint: "Business domain id — legal, finance",
  domainFieldPlaceholder: "legal, finance",
  typeKeyField: "Type key",
  typeKeyFieldHint: "Entry type within this domain — industry_tag",
  typeKeyFieldPlaceholder: "industry_tag",
  domainLabelField: "Display name",
  domainLabelPlaceholder: "Legal codes",
  domainFieldReadonlyHint: "Domain id cannot be changed after creation.",
  typeKeyReadonlyHint: "Built-in knowledge category uses a fixed type key.",
  typeKeyInUseHint:
    "This category already has entries; type key cannot be changed.",
  entriesEmpty: "No entries in this category yet.",
  createEntry: "New entry",
  editEntry: "Edit entry",
  sectionBasic: "Basic",
  sectionAttrs: "Extended attributes",
  entryCode: "Code",
  entryLabel: "Display name",
  entryCodePlaceholder: "auto-driving",
  entryLabelPlaceholder: "Smart driving",
  entryCodeHint: "auto-driving, smart-driving, adas",
  deleteEntryConfirm: "Delete this code-table entry? This cannot be undone.",
  entryCreated: "Entry created",
  entryUpdated: "Entry updated",
  entryDeleted: "Entry deleted",
  attrFields: {
    keywords: {
      label: "Keywords",
      placeholder: "autonomous driving\nsmart driving\nADAS",
      hint: "One item per line",
    },
    department: {
      label: "Departments",
      placeholder: "Smart driving BU",
      hint: "One item per line",
    },
    aliases: {
      label: "Aliases",
      placeholder: "Smart drive",
      hint: "One item per line",
    },
  },
  domains: {
    knowledge: {
      label: "Knowledge tags",
      description:
        "Document kinds, tags, and tag groups for knowledge import and retrieval.",
    },
  },
};

export const codeTableZhCN: CodeTableTranslations = {
  title: "码表管理",
  description: "按业务域维护共用码表，供标签、分类与下拉选项使用",
  listTitle: "码表列表",
  entriesListTitle: "码表列表",
  empty: "暂无已注册的码表域。",
  searchPlaceholder: "检索业务域…",
  searchEmpty: "没有匹配的业务域。",
  entriesSearchPlaceholder: "检索码表…",
  entriesSearchEmpty: "没有匹配的码表项。",
  countTotal: (count) => `${count} 条`,
  countFiltered: (shown, total) => `${shown} / ${total}`,
  openDomain: "管理",
  entryCount: (count) => `${count} 条`,
  deleteDomainConfirm: (label) =>
    `确定删除「${label}」下的全部码表？将清空整类码表且不可恢复。`,
  domainDeleted: (count) =>
    count === 1 ? "已删除 1 条码表" : `已删除 ${count} 条码表`,
  createDomain: "新建分类",
  editDomain: "编辑分类",
  domainCreated: "分类已创建",
  domainUpdated: "分类已更新",
  domainField: "业务域",
  domainFieldHint: "英文业务域标识：legal、finance",
  domainFieldPlaceholder: "legal、finance",
  typeKeyField: "类型键",
  typeKeyFieldHint: "该域下码表条目的 type_key：industry_tag",
  typeKeyFieldPlaceholder: "industry_tag",
  domainLabelField: "显示名称",
  domainLabelPlaceholder: "法务码表",
  domainFieldReadonlyHint: "业务域创建后不可修改。",
  typeKeyReadonlyHint: "内置 knowledge 分类的类型键不可修改。",
  typeKeyInUseHint: "该分类下已有码表条目，类型键不可修改。",
  entriesEmpty: "当前分类暂无码表条目。",
  createEntry: "新建码表",
  editEntry: "编辑码表",
  sectionBasic: "基本信息",
  sectionAttrs: "扩展属性",
  entryCode: "编码",
  entryLabel: "名称",
  entryCodePlaceholder: "auto-driving",
  entryLabelPlaceholder: "智能驾驶",
  entryCodeHint: "auto-driving、smart-driving、adas",
  deleteEntryConfirm: "确定删除此码表条目？此操作不可恢复。",
  entryCreated: "码表已创建",
  entryUpdated: "码表已更新",
  entryDeleted: "码表已删除",
  attrFields: {
    keywords: {
      label: "关键词",
      placeholder: "自动驾驶\n智能驾驶\nADAS",
      hint: "每行一个关键词",
    },
    department: {
      label: "部门",
      placeholder: "智能驾驶事业群",
      hint: "每行一个部门",
    },
    aliases: {
      label: "别名",
      placeholder: "智驾",
      hint: "每行一个别名",
    },
  },
  domains: {
    knowledge: {
      label: "知识库标签",
      description: "行业标签与知识库打标码表，用于分类与检索过滤。",
    },
  },
};
