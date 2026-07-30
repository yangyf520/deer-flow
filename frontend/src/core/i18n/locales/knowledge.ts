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
  editSpace: string;
  spaceUpdated: string;
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
  deleting: string;
  fieldKind: string;
  fieldKindHint: string;
  editTags: string;
  uploadTagsHint: string;
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
  topKPrefix: string;
  topKSuffix: string;
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
  tagGroups: Record<"national" | "company", string>;
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
  editSpace: "Edit space",
  spaceUpdated: "Space updated",
  fieldName: "Name",
  namePlaceholder: "e.g. Product docs",
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
  filterAllKinds: "All kinds",
  selectKind: "Filter by kind",
  searchFilename: "Search filename…",
  noMatchingDocs: "No documents match the current filters",
  emptyDocs: "No documents yet — upload a file to get started",
  viewChunks: "View chunks",
  reindex: "Rebuild",
  reindexing: "Rebuilding…",
  reindexTooltip: "Re-run parsing and embedding",
  deleteTooltip: "Delete document",
  deleting: "Deleting…",
  fieldKind: "Document kind",
  fieldKindHint: "Kind controls parsing and chunking strategy",
  editTags: "Tags",
  uploadTagsHint: "Optional tags for policy lanes",
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
  evalDescription: "Run batch queries (top {count} hits shown per question)",
  needQuestion: "Enter at least one question",
  questionPlaceholder: "Evaluation question",
  deleteQuestion: "Remove question",
  addQuestion: "Add question",
  topKPrefix: "Top",
  topKSuffix: "hits per question",
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
    reference: "Reference",
    general: "General",
    sop: "SOP",
    case: "Case",
    faq: "FAQ",
  },
  scenarios: {
    "general-qa": "General Q&A",
    "policy-review": "Policy review",
  },
  tagGroups: {
    national: "National regulations",
    company: "Company policy",
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
  editSpace: "编辑空间",
  spaceUpdated: "空间已更新",
  fieldName: "名称",
  namePlaceholder: "例如：产品文档",
  fieldDescription: "描述",
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
  filterAllKinds: "全部类型",
  selectKind: "按类型筛选",
  searchFilename: "搜索文件名…",
  noMatchingDocs: "没有符合筛选条件的文档",
  emptyDocs: "还没有文档 — 上传文件开始使用",
  viewChunks: "查看分块",
  reindex: "重建",
  reindexing: "重建中…",
  reindexTooltip: "重新解析并嵌入",
  deleteTooltip: "删除文档",
  deleting: "删除中…",
  fieldKind: "文档类型",
  fieldKindHint: "类型决定解析与分块策略",
  editTags: "标签",
  uploadTagsHint: "制度通道的可选标签",
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
  roleLabel: "角色",
  upsertGrant: "保存授权",
  currentGrants: "当前授权",
  emptyGrants: "尚未配置授权",
  deleteGrantTooltip: "移除授权",
  evalTitle: "检索评测",
  evalDescription: "批量运行查询（每题展示前 {count} 条命中）",
  needQuestion: "请至少输入一个问题",
  questionPlaceholder: "评测问题",
  deleteQuestion: "删除问题",
  addQuestion: "添加问题",
  topKPrefix: "每题取前",
  topKSuffix: "条命中",
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
    reference: "参考",
    general: "通用",
    sop: "SOP",
    case: "案例",
    faq: "FAQ",
  },
  scenarios: {
    "general-qa": "通用问答",
    "policy-review": "制度预审",
  },
  tagGroups: {
    national: "国家法规",
    company: "公司制度",
  },
};
