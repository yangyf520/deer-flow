export type KnowledgeTranslations = {
  title: string;
  description: string;
  listTitle: string;
  countTotal: (count: number) => string;
  countFiltered: (shown: number, total: number) => string;
  searchPlaceholder: string;
  searchEmpty: string;
  emptyTitle: string;
  emptyDescription: string;
  emptySpaces: string;
  spaceCount: string;
  createSpace: string;
  catalogButton: string;
  catalogTitle: string;
  catalogDescription: string;
  catalogListTitle: string;
  catalogCountTotal: (count: number) => string;
  catalogCountFiltered: (shown: number, total: number) => string;
  catalogSearchPlaceholder: string;
  catalogSearchEmpty: string;
  catalogEmpty: string;
  catalogKinds: string;
  catalogTagGroups: string;
  catalogScenarioCode: string;
  catalogSpaceCode: string;
  catalogSwitchSpace: string;
  catalogAllSpaces: string;
  catalogMigrateHostTitle: string;
  catalogMigrateHostDescription: string;
  catalogMigrateHostSelect: string;
  catalogMigrateHostCurrentLabel: string;
  catalogMigrateHostCurrent: (name: string) => string;
  catalogMigrated: (count: number) => string;
  catalogOpenSpace: string;
  createScenario: string;
  editScenario: string;
  catalogFieldLabel: string;
  catalogFieldLabelPlaceholder: string;
  catalogCodePlaceholder: string;
  catalogCodeHint: string;
  catalogCodeInvalid: string;
  catalogDescriptionPlaceholder: string;
  catalogDeleteConfirm: string;
  scenarioCreated: string;
  scenarioUpdated: string;
  scenarioDeleted: string;
  fieldTopK: string;
  fieldScore: string;
  editSpace: string;
  editDocument: string;
  documentUpdated: string;
  sectionBasic: string;
  sectionDocument: string;
  sectionUpload: string;
  sectionUploadFile: string;
  spaceUpdated: string;
  spaceDeleted: string;
  fieldName: string;
  namePlaceholder: string;
  fieldDescription: string;
  descriptionPlaceholder: string;
  fieldAccess: string;
  fieldScenario: string;
  selectScenario: string;
  fieldAllowedKinds: string;
  allAllowedKinds: string;
  selectAllowedKinds: string;
  bindScenario: string;
  unbound: string;
  documents: string;
  eval: string;
  grants: string;
  docsSubtitle: string;
  docsList: string;
  docsCount: string;
  docsCountFiltered: string;
  upload: string;
  uploading: string;
  uploadDialogTitle: string;
  uploadDialogDescription: string;
  uploadModeLabel: string;
  uploadModeUnstructured: string;
  uploadModeStructured: string;
  uploadModeUnstructuredHint: string;
  uploadModeStructuredHint: string;
  uploadFileLabel: string;
  uploadSegmentPromptLabel: string;
  parseAction: string;
  vectorize: string;
  vectorizing: string;
  parsePreviewTitle: string;
  selectFile: string;
  noFileSelected: string;
  structuredParsing: string;
  structuredImported: (segments: number) => string;
  structuredReindexed: string;
  filterAllKinds: string;
  selectKind: string;
  searchFilename: string;
  noMatchingDocs: string;
  emptyDocs: string;
  viewChunks: string;
  reindex: string;
  reindexing: string;
  reindexTooltip: string;
  deleteTooltip: string;
  deleteAllButton: string;
  deleteAllTitle: string;
  deleteAllDescription: (count: number) => string;
  deleteAllSuccess: string;
  stopProcessingTooltip: string;
  deleting: string;
  fieldKind: string;
  fieldKindHint: string;
  editTags: string;
  dedupedNotice: string;
  chunks: string;
  chunksSummary: string;
  searchChunks: string;
  chunksLoading: string;
  chunksEmpty: string;
  searchChunksEmpty: string;
  charCount: string;
  emptyText: string;
  grantsTitle: string;
  grantsSpace: string;
  addGrant: string;
  grantsUpstreamHint: string;
  subjectType: string;
  user: string;
  dept: string;
  userPlaceholder: string;
  deptPlaceholder: string;
  roleLabel: string;
  upsertGrant: string;
  currentGrants: string;
  emptyGrants: string;
  deleteGrantTooltip: string;
  evalTitle: string;
  evalDescription: string;
  needQuestion: string;
  questionPlaceholder: string;
  deleteQuestion: string;
  addQuestion: string;
  runningEval: string;
  runEval: string;
  questionsCount: string;
  totalLatency: string;
  avgLatency: string;
  hitChunks: string;
  docsTouched: string;
  emptyRecallCount: string;
  lowTopCount: string;
  unknownSource: string;
  emptySnippet: string;
  lowScore: string;
  source: string;
  section: string;
  matchedContent: string;
  collapseFull: string;
  expandFull: string;
  citable: string;
  noHits: string;
  hitsSummary: string;
  docsInvolved: string;
  scoreGap: string;
  emptyRecallHint: string;
  collapseHidden: string;
  expandHidden: string;
  access: Record<"open" | "members" | "private", string>;
  accessHint: Record<"open" | "members" | "private", string>;
  role: Record<"viewer" | "editor" | "publisher" | "admin", string>;
  status: Record<"ready" | "failed" | "processing", string>;
  phase: Record<"queued" | "parsing" | "embedding", string>;
  parseQuality: Record<"ok" | "degraded" | "failed", string>;
  parseQualityHint: Record<"ok" | "degraded" | "failed", string>;
  kinds: Record<string, string>;
  scenarios: Record<string, string>;
  tagGroups: Record<string, string>;
  tags?: Record<string, string>;
};

export const knowledgeEnUS: KnowledgeTranslations = {
  title: "Knowledge",
  description: "Manage knowledge spaces, documents, and retrieval scenarios",
  listTitle: "All spaces",
  countTotal: (count) => (count === 1 ? "1 space" : `${count} spaces`),
  countFiltered: (shown, total) => `${shown} / ${total}`,
  searchPlaceholder: "Search spaces…",
  searchEmpty: "No spaces match your search.",
  emptyTitle: "No knowledge spaces yet",
  emptyDescription: "Create a space to upload documents and enable retrieval.",
  emptySpaces: "No knowledge spaces yet",
  spaceCount: "{count} spaces",
  createSpace: "New space",
  catalogButton: "Scenarios",
  catalogTitle: "Catalog management",
  catalogDescription:
    "Maintain code-table entries for spaces and other modules.",
  catalogListTitle: "Catalog management",
  catalogCountTotal: (count) => `Catalog count ${count}`,
  catalogCountFiltered: (shown, total) => `Catalog count ${shown} / ${total}`,
  catalogSearchPlaceholder: "Search catalog…",
  catalogSearchEmpty: "No matching catalog entries.",
  catalogEmpty: "No catalog entries yet.",
  catalogKinds: "Document kinds",
  catalogTagGroups: "Tag groups",
  catalogScenarioCode: "Code",
  catalogSpaceCode: "Knowledge space",
  catalogSwitchSpace: "Switch space",
  catalogAllSpaces: "All spaces",
  catalogMigrateHostTitle: "Switch knowledge space",
  catalogMigrateHostDescription:
    "Move all catalog entries to another knowledge space. Document spaces linked to each entry are unchanged.",
  catalogMigrateHostSelect: "Target space",
  catalogMigrateHostCurrentLabel: "Current space",
  catalogMigrateHostCurrent: (name) => `Current: ${name}`,
  catalogMigrated: (count) =>
    count === 1
      ? "Moved 1 catalog entry to the selected space"
      : `Moved ${count} catalog entries to the selected space`,
  catalogOpenSpace: "Open space",
  createScenario: "New entry",
  editScenario: "Edit entry",
  catalogFieldLabel: "Display name",
  catalogFieldLabelPlaceholder: "e.g. Policy review",
  catalogCodePlaceholder: "e.g. finance-review",
  catalogCodeHint:
    "Lowercase letters, numbers, and hyphens. Also used as the linked knowledge space id.",
  catalogCodeInvalid:
    "Use lowercase letters, numbers, and hyphens (e.g. finance-review).",
  catalogDescriptionPlaceholder: "What this entry is for",
  catalogDeleteConfirm:
    "Delete this catalog entry and its linked knowledge space? This cannot be undone.",
  scenarioCreated: "Catalog entry created",
  scenarioUpdated: "Catalog entry updated",
  scenarioDeleted: "Catalog entry deleted",
  fieldTopK: "Top K",
  fieldScore: "Score threshold",
  editSpace: "Edit space",
  editDocument: "Edit document",
  documentUpdated: "Document updated",
  sectionBasic: "Basics",
  sectionDocument: "Document",
  sectionUpload: "Upload",
  sectionUploadFile: "Select file",
  spaceUpdated: "Space updated",
  spaceDeleted: "Space deleted",
  fieldName: "Space ID",
  namePlaceholder: "e.g. policy-reviewer",
  fieldDescription: "Description",
  descriptionPlaceholder: "What this space is for",
  fieldAccess: "Access",
  fieldScenario: "Scenario",
  selectScenario: "Select scenario",
  fieldAllowedKinds: "Allowed document kinds",
  allAllowedKinds: "All kinds in scenario",
  selectAllowedKinds: "Select kind",
  bindScenario: "Bind scenario",
  unbound: "Unbound",
  documents: "Documents",
  eval: "Eval",
  grants: "Grants",
  docsSubtitle: "Upload and manage documents in this space",
  docsList: "Documents",
  docsCount: "{count} documents",
  docsCountFiltered: "{filtered} / {total}",
  upload: "Upload",
  uploading: "Uploading…",
  uploadDialogTitle: "Upload document",
  uploadDialogDescription: "Pick a split mode and file to index in this space.",
  uploadModeLabel: "Split mode",
  uploadModeUnstructured: "Auto chunk",
  uploadModeStructured: "Structured",
  uploadModeUnstructuredHint:
    "Upload the file directly. DeerFlow splits and embeds it with the default ingest pipeline.",
  uploadModeStructuredHint:
    "Run the document parse API first, then store the segmented result in this knowledge space.",
  uploadFileLabel: "File",
  uploadSegmentPromptLabel: "Segment prompt",
  parseAction: "Parse",
  vectorize: "Vectorize",
  vectorizing: "Vectorizing…",
  parsePreviewTitle: "Parse result",
  selectFile: "Choose file",
  noFileSelected: "No file selected",
  structuredParsing: "Parsing…",
  structuredImported: (segments) =>
    segments === 1
      ? "Structured document imported (1 segment)."
      : `Structured document imported (${segments} segments).`,
  structuredReindexed: "Structured re-index completed.",
  filterAllKinds: "All",
  selectKind: "Filter by kind",
  searchFilename: "Search filename…",
  noMatchingDocs: "No documents match the current filters",
  emptyDocs: "No documents yet — upload a file to get started",
  viewChunks: "View chunks",
  reindex: "Rebuild",
  reindexing: "Rebuilding…",
  reindexTooltip: "Re-run parsing and embedding",
  deleteTooltip: "Delete document",
  deleteAllButton: "Delete all",
  deleteAllTitle: "Delete all documents",
  deleteAllDescription: (count) =>
    `Permanently delete all ${count} documents in this space. This cannot be undone.`,
  deleteAllSuccess: "All documents deleted",
  stopProcessingTooltip: "Stop processing and delete",
  deleting: "Deleting…",
  fieldKind: "Document kind",
  fieldKindHint: "Kind controls parsing and chunking strategy",
  editTags: "Tags",
  dedupedNotice: "Duplicate upload skipped",
  chunks: "Chunks",
  chunksSummary: "{count} chunks",
  searchChunks: "Search chunks…",
  chunksLoading: "Loading chunks…",
  chunksEmpty: "No chunks yet",
  searchChunksEmpty: "No chunks match your search",
  charCount: "{count} chars",
  emptyText: "(empty)",
  grantsTitle: "Access grants",
  grantsSpace: "Space {id}",
  addGrant: "Add grant",
  grantsUpstreamHint:
    "Grants are managed upstream; changes here sync to the knowledge service.",
  subjectType: "Subject type",
  user: "User",
  dept: "Department",
  userPlaceholder: "User ID or email",
  deptPlaceholder: "Department ID",
  roleLabel: "Role",
  upsertGrant: "Save grant",
  currentGrants: "Current grants",
  emptyGrants: "No grants configured",
  deleteGrantTooltip: "Remove grant",
  evalTitle: "Retrieval eval",
  evalDescription: "Run batch queries and review recall results",
  needQuestion: "Enter at least one question",
  questionPlaceholder: "Evaluation question",
  deleteQuestion: "Remove question",
  addQuestion: "Add question",
  runningEval: "Running…",
  runEval: "Run eval",
  questionsCount: "{count} questions",
  totalLatency: "Total {latency}",
  avgLatency: "Avg {latency}",
  hitChunks: "{count} hits",
  docsTouched: "{count} docs",
  emptyRecallCount: "{count} empty recalls",
  lowTopCount: "{count} low top scores",
  unknownSource: "Unknown source",
  emptySnippet: "(no snippet)",
  lowScore: "Low score",
  source: "Source: {source}",
  section: "Section: {section}",
  matchedContent: "Matched content",
  collapseFull: "Show less",
  expandFull: "Show full text",
  citable: "Cite as: {cite}",
  noHits: "No hits",
  hitsSummary: "{count} hits · top {score}",
  docsInvolved: "{count} docs",
  scoreGap: "Gap {gap}",
  emptyRecallHint: "No evidence returned — check indexing or query wording",
  collapseHidden: "Show fewer ({count} hidden)",
  expandHidden: "Show all ({count} more)",
  access: {
    open: "Open",
    members: "Members only",
    private: "Private",
  },
  accessHint: {
    open: "Visible to all workspace users",
    members: "Only members with a grant",
    private: "Only admins and explicit grants",
  },
  role: {
    viewer: "Viewer",
    editor: "Editor",
    publisher: "Publisher",
    admin: "Admin",
  },
  status: {
    ready: "Ready",
    failed: "Failed",
    processing: "Processing",
  },
  phase: {
    queued: "Queued",
    parsing: "Parsing",
    embedding: "Embedding",
  },
  parseQuality: {
    ok: "Parse OK",
    degraded: "Degraded parse",
    failed: "Parse failed",
  },
  parseQualityHint: {
    ok: "Document parsed successfully",
    degraded: "Partial or lossy extraction — review chunks",
    failed: "Could not extract usable text",
  },
  kinds: {
    policy: "Policy",
    reference: "Regulations",
    general: "General",
    sop: "SOP",
    case: "Case",
    faq: "FAQ",
  },
  scenarios: {
    auto: "Autonomous driving",
    health: "Smart healthcare",
    fintech: "FinTech",
    "smart-city": "Smart city",
    education: "Education",
    business: "Business",
    "culture-media": "Culture & entertainment",
  },
  tagGroups: {
    national: "National regulations",
    company: "Company policy",
  },
  tags: {
    statute: "Statute",
    "national-law": "National law",
    "company-policy": "Company policy",
  },
};

export const knowledgeZhCN: KnowledgeTranslations = {
  title: "知识库",
  description: "管理知识空间、文档与检索场景",
  listTitle: "全部空间",
  countTotal: (count) => `${count} 个知识空间`,
  countFiltered: (shown, total) => `${shown} / ${total}`,
  searchPlaceholder: "搜索知识空间…",
  searchEmpty: "没有匹配的知识空间。",
  emptyTitle: "还没有知识空间",
  emptyDescription: "创建空间以上传文档并启用检索。",
  emptySpaces: "还没有知识空间",
  spaceCount: "{count} 个空间",
  createSpace: "新建空间",
  catalogButton: "场景管理",
  catalogTitle: "码表管理",
  catalogDescription: "维护知识库码表，供空间等业务模块选用。",
  catalogListTitle: "码表管理",
  catalogCountTotal: (count) => `码表数量 ${count}`,
  catalogCountFiltered: (shown, total) => `码表数量 ${shown} / ${total}`,
  catalogSearchPlaceholder: "检索码表信息…",
  catalogSearchEmpty: "没有匹配的码表项。",
  catalogEmpty: "暂无码表条目。",
  catalogKinds: "文档分类",
  catalogTagGroups: "标签组",
  catalogScenarioCode: "编码",
  catalogSpaceCode: "知识库",
  catalogSwitchSpace: "切换知识库",
  catalogAllSpaces: "全部知识库",
  catalogMigrateHostTitle: "切换知识库",
  catalogMigrateHostDescription:
    "将全部码表条目迁移到所选知识库。各条目关联的文档空间不会变更。",
  catalogMigrateHostSelect: "目标知识库",
  catalogMigrateHostCurrentLabel: "当前知识库",
  catalogMigrateHostCurrent: (name) => `当前：${name}`,
  catalogMigrated: (count) => `已将 ${count} 条码表迁移至所选知识库`,
  catalogOpenSpace: "打开知识库",
  createScenario: "新建码表",
  editScenario: "编辑码表",
  catalogFieldLabel: "名称",
  catalogFieldLabelPlaceholder: "例如：制度预审",
  catalogCodePlaceholder: "例如：finance-review",
  catalogCodeHint: "小写英文、数字与连字符；同时作为关联知识空间的编码。",
  catalogCodeInvalid: "请使用小写英文、数字与连字符（如 finance-review）。",
  catalogDescriptionPlaceholder: "此码表条目的用途",
  catalogDeleteConfirm: "确定删除此码表条目及关联的知识库？此操作不可恢复。",
  scenarioCreated: "码表已创建",
  scenarioUpdated: "码表已更新",
  scenarioDeleted: "码表已删除",
  fieldTopK: "召回条数",
  fieldScore: "相似度阈值",
  editSpace: "编辑空间",
  editDocument: "编辑文档",
  documentUpdated: "文档已更新",
  sectionBasic: "基本信息",
  sectionDocument: "文档属性",
  sectionUpload: "上传设置",
  sectionUploadFile: "文件选择",
  spaceUpdated: "空间已更新",
  spaceDeleted: "空间已删除",
  fieldName: "空间编号",
  namePlaceholder: "例如：policy-reviewer",
  fieldDescription: "空间描述",
  descriptionPlaceholder: "这个空间的用途",
  fieldAccess: "访问权限",
  fieldScenario: "场景",
  selectScenario: "选择场景",
  fieldAllowedKinds: "允许的文档类型",
  allAllowedKinds: "场景内全部类型",
  selectAllowedKinds: "选择类型",
  bindScenario: "绑定场景",
  unbound: "未绑定",
  documents: "文档",
  eval: "评测",
  grants: "授权",
  docsSubtitle: "在此空间上传和管理文档",
  docsList: "文档",
  docsCount: "{count} 个文档",
  docsCountFiltered: "{filtered} / {total}",
  upload: "上传",
  uploading: "上传中…",
  uploadDialogTitle: "上传文档",
  uploadDialogDescription: "选择拆分方式并上传文件，写入当前知识空间。",
  uploadModeLabel: "拆分方式",
  uploadModeUnstructured: "自动分块",
  uploadModeStructured: "结构化",
  uploadModeUnstructuredHint: "直接上传文件，按默认流水线拆分并向量化。",
  uploadModeStructuredHint: "先调用文档解析接口切条，再将解析结果写入知识库。",
  uploadFileLabel: "文件",
  uploadSegmentPromptLabel: "解析提示词",
  parseAction: "解析",
  vectorize: "向量化",
  vectorizing: "向量化中…",
  parsePreviewTitle: "解析结果",
  selectFile: "选择文件",
  noFileSelected: "尚未选择文件",
  structuredParsing: "解析中…",
  structuredImported: (segments) =>
    segments === 1
      ? "结构化文档已入库（1 个片段）。"
      : `结构化文档已入库（${segments} 个片段）。`,
  structuredReindexed: "结构化重建已完成。",
  filterAllKinds: "全部",
  selectKind: "按类型筛选",
  searchFilename: "搜索文件名…",
  noMatchingDocs: "没有符合筛选条件的文档",
  emptyDocs: "还没有文档 — 上传文件开始使用",
  viewChunks: "查看分块",
  reindex: "重建",
  reindexing: "重建中…",
  reindexTooltip: "重新解析并嵌入",
  deleteTooltip: "删除文档",
  deleteAllButton: "删除全部",
  deleteAllTitle: "删除全部文档",
  deleteAllDescription: (count) =>
    `将永久删除此知识库中的全部 ${count} 个文档，且无法恢复。`,
  deleteAllSuccess: "已全部删除",
  stopProcessingTooltip: "停止处理并删除",
  deleting: "删除中…",
  fieldKind: "知识分类",
  fieldKindHint: "类型决定解析与分块策略",
  editTags: "文档标签",
  dedupedNotice: "已跳过重复上传",
  chunks: "分块",
  chunksSummary: "{count} 个分块",
  searchChunks: "搜索分块…",
  chunksLoading: "加载分块中…",
  chunksEmpty: "还没有分块",
  searchChunksEmpty: "没有匹配的分块",
  charCount: "{count} 字符",
  emptyText: "（空）",
  grantsTitle: "访问授权",
  grantsSpace: "空间 {id}",
  addGrant: "添加授权",
  grantsUpstreamHint: "授权由上游管理；此处的变更会同步到知识服务。",
  subjectType: "主体类型",
  user: "用户",
  dept: "部门",
  userPlaceholder: "用户 ID 或邮箱",
  deptPlaceholder: "部门 ID",
  roleLabel: "我的角色",
  upsertGrant: "保存授权",
  currentGrants: "当前授权",
  emptyGrants: "尚未配置授权",
  deleteGrantTooltip: "移除授权",
  evalTitle: "检索评测",
  evalDescription: "批量运行查询，查看召回结果",
  needQuestion: "请至少输入一个问题",
  questionPlaceholder: "评测问题",
  deleteQuestion: "删除问题",
  addQuestion: "添加问题",
  runningEval: "运行中…",
  runEval: "运行评测",
  questionsCount: "{count} 个问题",
  totalLatency: "总计 {latency}",
  avgLatency: "平均 {latency}",
  hitChunks: "{count} 条命中",
  docsTouched: "{count} 篇文档",
  emptyRecallCount: "{count} 条空召回",
  lowTopCount: "{count} 条低分首位",
  unknownSource: "未知来源",
  emptySnippet: "（无摘要）",
  lowScore: "低分",
  source: "来源：{source}",
  section: "章节：{section}",
  matchedContent: "匹配内容",
  collapseFull: "收起",
  expandFull: "展开全文",
  citable: "引用：{cite}",
  noHits: "无命中",
  hitsSummary: "{count} 条命中 · 最高 {score}",
  docsInvolved: "{count} 篇文档",
  scoreGap: "分差 {gap}",
  emptyRecallHint: "未返回证据 — 请检查索引或问题表述",
  collapseHidden: "收起（隐藏 {count} 条）",
  expandHidden: "展开全部（还有 {count} 条）",
  access: {
    open: "开放",
    members: "仅成员",
    private: "私有",
  },
  accessHint: {
    open: "工作区所有用户可见",
    members: "仅有授权的成员",
    private: "仅管理员与显式授权",
  },
  role: {
    viewer: "查看者",
    editor: "编辑者",
    publisher: "发布者",
    admin: "管理员",
  },
  status: {
    ready: "就绪",
    failed: "失败",
    processing: "处理中",
  },
  phase: {
    queued: "排队中",
    parsing: "解析中",
    embedding: "嵌入中",
  },
  parseQuality: {
    ok: "解析正常",
    degraded: "解析降级",
    failed: "解析失败",
  },
  parseQualityHint: {
    ok: "文档解析成功",
    degraded: "提取不完整 — 请核对分块",
    failed: "无法提取可用文本",
  },
  kinds: {
    policy: "制度",
    reference: "法规",
    general: "通用",
    sop: "SOP",
    case: "案例",
    faq: "FAQ",
  },
  scenarios: {
    auto: "自动驾驶",
    health: "智慧医疗",
    fintech: "金融科技",
    "smart-city": "智慧城市",
    education: "教育",
    business: "商业",
    "culture-media": "文娱",
  },
  tagGroups: {
    national: "国家法规",
    company: "公司制度",
  },
  tags: {
    statute: "法律",
    "national-law": "国家法律",
    "company-policy": "公司制度",
  },
};
