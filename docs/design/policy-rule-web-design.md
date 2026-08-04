# 规则管理 · 法务 Web 设计

> **读者**：法务健康度 / 规则库 **Web 项目**前端与 BFF 开发。  
> **职责**：产品页面、业务流程、PRD 自查编排、计分与审计展示；**AI 切条**调 DeerFlow [`doc-parse-design.md`](./doc-parse-design.md)；**确认发布后向量化与法规检索**调 DeerFlow [`knowledge-design.md`](./knowledge-design.md)；Web **不直连 LLM / 向量库**。

---

## 1. 系统边界

```text
┌─────────────────────────────────────┐
│  法务 Web                            │
│  · 法律库 / 规则树 / 码表 管理页      │
│  · PRD 上传、多轮自查、报告、高亮      │
│  · 计分汇总、审计展示                  │
└──────────────┬──────────────────────┘
               │ HTTPS（REST）
               ▼
┌─────────────────────────────────────┐
│  DeerFlow Gateway                  │
│  · POST /api/doc/parse             │
│  · POST /api/knowledge/v1/…        │
│    import（向量化）/ search（检索）  │
└─────────────────────────────────────┘
```

| Web 做 | Web 不做 |
|--------|----------|
| 全部业务页面、CRUD、落库、计分、审计 | Docling、LLM、embed 引擎直连 |
| 确认发布后 **DeerFlow knowledge 向量化** | 自管 VectorStore |
| 法务 prompt、`resolve_refs` | `run_oneshot_llm` 直连 |
| PRD 自查编排 | Agent thread（制度预审另入口） |

---

## 2. 端到端业务流程

### 2.1 法律库（自动 + 人工）

```text
1. 用户选 category(L1/L2/L3) + 行业 tags + 文件 [+ 可选覆盖 segment_prompt]
2. Web → POST /api/doc/parse（**必带**法务 segment_prompt）→ 得 `data`、`meta`
3. Web 从 `data` 写入 rule_spaces（draft）+ rule_details
4. 跳转 /rules/{spaceId}：编辑主表 meta、预览/改明细
5. 用户点「确认发布」→ Web BFF 调 DeerFlow knowledge **逐条 import 向量化**（§5）→ `status=active`
6. Web 展示 `embedded_at` / 条款数
```

废止/新版：Web 只允许改旧 space **status**；新版走 **重新上传**（新 space_id）。

### 2.2 规则树（全人工）

```text
1. Web 维护一二级维度 + 检查点（Web/BFF API + 自有 SQL）
2. 配分：max_score、weight、score_type、mandatory、industry_tags
3. legal_refs：picker 选 rule_spaces → rule_details 明细行
4. 保存前 Web 侧校验权重和、一票否决等
```

### 2.3 确认发布与向量化（DeerFlow knowledge）

```text
用户点「确认发布」
  → 校验 status=draft、明细非空
  → BFF：对每条 rule_details 调用 DeerFlow knowledge import（§5.2）
  → 全部成功 → rule_spaces.status = active；attrs.embedded_at = now()
  → 任一条失败 → 保持 draft，返回失败明细列表（可重试 confirm）
```

| 项 | 规则 |
|----|------|
| embed 文本 | `space.title + chapter_path + segment_label + body`（Web 拼好写入 import 文件） |
| 向量 metadata | 经 document `attrs` 同步到分片：`rule_space_id`, `detail_id`, `category`, `segment_label` |
| 检索过滤 | `POST /api/knowledge/v1/search` + `spaces` + `tags` + `kinds`（§5.3） |
| 鉴权 | BFF 持 `dfk_` 或用户 session；需 `knowledge:write`（import）、`knowledge:read`（search） |

### 2.4 引用解析 `resolve_refs`（Web/BFF）

切条落库后 **代码步**（不调模型）：

| 类型 | 做法 |
|------|------|
| 同文档「见第 X 条」 | `refs[].target_detail_id` |
| 「前条 / 上一款」 | 解析为绝对 `segment_label` |
| 跨文档引用 | `refs[].external`；库中无 space 则标记 unresolved |
| 深度 | **仅 1 跳** |
| 未解析 | `refs[].status = unresolved` |

输入来自 `data.details[].ref_labels`（见 §4.1）或人工编辑后的 `refs` 字段。

### 2.5 PRD 健康度自查（P2）

```text
每轮自查：
1. Web 读 PRD（表格→「列名：值」、折叠展开、保留标题层级）
2. Web 可选：PRD 向量化（若 DeerFlow 提供 PRD search，或 Web 自管 PRD 索引）
3. 按 PRD 行业 → Web `GET /tree/checkpoints?industry_tags=…` 得适用检查点
4. 对每个检查点 / 每段 PRD：
     · BFF 调 DeerFlow `POST /api/knowledge/v1/search`（§5.3）得 Evidence
     · 从 Evidence.metadata.detail_id 查 rule_details + 检查点配置
5. Web 算分：权重、一票否决、一级维度汇总
6. 结论：同检查点多位置单独编号，满足与否综合判定；原文 offset 高亮在 Web 存/算
```

---

## 3. 页面与路由（建议）

```text
/rules                          # 法律库列表 + 上传入口
/rules/upload                   # category、tags、文件、segment_prompt
/rules/{spaceId}                # 主表 meta + 明细表 +「确认发布」
/rules/{spaceId}/details/{id}   # 单条明细编辑（可选）

/rules/tree                     # 规则树（对标飞书规则树 Sheet）
/rules/tree/checkpoints/new
/rules/tree/checkpoints/{id}    # legal_refs picker

/settings/codes?domain=legal    # pub_codes 管理

/prd                            # PRD 列表（Web 自有表，若需要）
/prd/{id}/review                # 多轮自查、报告、审计高亮
```

上传表单对标知识库：**选分类 + 选文件**；分类来自 Web 码表 `pub_codes`（`domain=legal`），**不选** knowledge scenario。

---

## 4. 调用 doc-parse（接口 + 提示词）

平台契约见 [`doc-parse-design.md`](./doc-parse-design.md)。Web **只调这一接口**做 AI 切条；prompt 与落库映射均在 Web。

### 4.1 调用关系

```text
浏览器 → Web BFF  POST /spaces（或 /spaces/upload）
           │
           ├─ 1. 组装 segment_prompt（§4.2）
           ├─ 2. 转发 DeerFlow  POST /api/doc/parse（§4.3）
           ├─ 3. 校验 data，映射 rule_spaces + rule_details（§4.4）
           └─ 4. resolve_refs（§2.4）→ 返回 space_id
```

前端 **不直连** DeerFlow；BFF 持有 Gateway 凭证（与用户 session 或 service token，按部署约定）。

### 4.2 提示词（Web 负责）

| 项 | 说明 |
|----|------|
| 默认模板 | Web `prompts/legal-segment.ts`（或 BFF 常量） |
| 用户覆盖 | 上传页「高级 · 切条 prompt」→ 非空则 **整段替换** 默认模板 |
| 传给 DeerFlow | 表单字段名 **`segment_prompt`**，原样放入 multipart |
| 留档 | `rule_spaces.attrs.segment_prompt`（最终生效全文） |
| 严格校验 | 可选同传 **`output_schema`**（JSON Schema 字符串，与 prompt 一致） |

**prompt 必须包含：** 切条规则 + **输出 JSON 示例**（见 [`doc-parse-design.md`](./doc-parse-design.md) §3）。DeerFlow 不内置法务字段。

法务默认输出形状（写在 prompt 里，非平台硬编码）：

```json
{
  "title": "文档标题",
  "details": [
    {
      "segment_label": "第7条",
      "chapter_path": "第二章 …",
      "body": "……",
      "ref_labels": ["第6条"]
    }
  ]
}
```

多批 Docling 块时保持相同顶层结构；DeerFlow 对 `details[]` **append merge**。

**prompt 模板示意（BFF 拼接，非 DeerFlow 代码）：**

```text
你是法规文档切条助手。根据下文「文档块」切分为条款 JSON。
要求：只输出一个 JSON 对象，不要 markdown 围栏；保留条号 segment_label、章节 chapter_path、正文 body；引用写 ref_labels。
输出格式示例：
{"title":"…","details":[{"segment_label":"第1条","chapter_path":"…","body":"…","ref_labels":[]}]}

文档块：
---
{docling_block_text}
---
```

用户自定义 prompt 时，仍须约定 **`details[]`** 数组以便平台 merge（或 P1 由 BFF 自行 merge `data.batches`）。

### 4.3 DeerFlow 接口

| 项 | 值 |
|----|-----|
| 方法 / 路径 | **`POST /api/doc/parse`** |
| Base URL | DeerFlow Gateway（经 Nginx 一般为 `{origin}/api/doc/parse`） |
| Content-Type | `multipart/form-data` |
| 鉴权 | 与 Gateway 一致（如 Bearer / Cookie）；规划同 input-polish：`runs:create` |

**请求字段：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `file` | 是 | 用户上传的法规文件 |
| `segment_prompt` | 是 | §4.2 组装后的完整 prompt |
| `output_schema` | 否 | 可选；失败时 DeerFlow 返回 422 |

**成功响应（200）：**

```json
{
  "data": {
    "title": "某某法",
    "details": [ { "segment_label": "第7条", "chapter_path": "…", "body": "…", "ref_labels": [] } ]
  },
  "meta": {
    "source_filename": "law.pdf",
    "segment_prompt_hash": "sha256:…",
    "block_count": 8,
    "batch_count": 1
  }
}
```

| 字段 | Web 用法 |
|------|----------|
| `data` | 落库来源（§4.4） |
| `meta.source_filename` | `rule_spaces.attrs.source_filename` |
| `meta.segment_prompt_hash` | 可选审计；对比 prompt 是否变更 |
| `meta.batch_count` | UI 展示「分 N 批解析」 |

**错误（BFF 需转前端可读文案）：**

| 状态 | 含义 | Web 处理 |
|------|------|----------|
| 422 | JSON / schema 校验失败 | 提示调整 prompt 或重试 |
| 413 / 400 | 文件过大或参数非法 | 表单校验 |
| 502 / 504 | Docling 或模型超时 | 可重试；P1 改异步 job |
| 401 / 403 | 鉴权失败 | 登录 / 配置 service token |

**BFF 转发示例（伪代码）：**

```typescript
const form = new FormData();
form.append("file", file);
form.append("segment_prompt", resolveSegmentPrompt(userPromptOverride));
if (outputSchema) form.append("output_schema", JSON.stringify(outputSchema));

const res = await fetch(`${DEERFLOW_ORIGIN}/api/doc/parse`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` },
  body: form,
});
const { data, meta } = await res.json();
```

### 4.4 `data` → 落库

| `data` 字段 | 写入 |
|-------------|------|
| `title` | `rule_spaces.title`（可编辑） |
| `details[].segment_label` | `rule_details.segment_label` |
| `details[].chapter_path` | `rule_details.chapter_path` |
| `details[].body` | `rule_details.body` |
| `details[].ref_labels` | 落库后 `resolve_refs` → `refs` |
| 表单 `category`、`tags` | `rule_spaces`；冗余到每条 `rule_details.category` |
| — | `rule_spaces.status = draft`；`sort_key` = 数组下标 |

`meta` **不入业务表**（除 `source_filename` 等 attrs 可选拷贝）。

### 4.5 与 Web BFF 上传 API 的关系

| 层 | 路径 | 说明 |
|----|------|------|
| 前端 | `POST /spaces` 或 `POST /spaces/upload` | 带 file、category、tags；BFF 始终组装 `segment_prompt` |
| BFF 内部 | `POST {DEERFLOW}/api/doc/parse` | §4.3 |
| BFF 响应 | `{ space_id, detail_count, meta }` | 不暴露 DeerFlow 原始响应给前端（可选 `preview`） |

---

## 5. 调用 knowledge（确认向量化 + 检索）

平台契约见 [`knowledge-design.md`](./knowledge-design.md)。**用户确认发布法规后，向量写入与检索均走 DeerFlow knowledge**，Web 不自建向量库。

### 5.1 知识空间映射

| 项 | 说明 |
|----|------|
| DeerFlow 容器 | 一个（或每租户一个）knowledge **Space**，专用于法务法规向量 |
| Web 配置 | BFF 环境变量 `LEGAL_KNOWLEDGE_SPACE_ID`，或 `rule_spaces.attrs.knowledge_space_id` |
| 文档 kind | `legal-clause`（须在 space `allowed_kinds` 与 `config.yaml` `knowledge.kinds` 中登记） |
| 业务主库 | `rule_spaces` / `rule_details` 仍在 **Web SQL**；knowledge 仅存向量与检索用 document |

### 5.2 确认发布：逐条向量化

用户对 `rule_space` 点「确认发布」后，BFF **循环** `rule_details`，每条调用一次 import（已切好的正文，**不再** doc/parse）：

| 项 | 值 |
|----|-----|
| 方法 / 路径 | **`POST /api/doc/embed/{space_id}`** |
| `file` | UTF-8 文本字节（内容为 embed 文本，文件名如 `{detail_id}.txt`） |
| `kind` | `legal-clause` |
| `tags[]` | `rule_spaces.tags` + 可选 `category` slug |
| `title` | `{rule_spaces.title} · {segment_label}` |

import 同步完成解析+切块+**embed**（见 knowledge §5.1）。返回 `doc_id` 后：

| 步骤 | API |
|------|-----|
| 写入业务 attrs | **`PATCH /api/knowledge/v1/spaces/{space_id}/documents/{doc_id}`** → `attrs`: `{ "rule_space_id", "detail_id", "segment_label", "category" }` |
| 回写 Web | `rule_details.attrs.knowledge_doc_id = doc_id` |

`patch_document_metadata` 会把 `attrs` 同步到向量分片 metadata，供 search 带回 `detail_id`。

**失败与重试：**

- 单条 import 失败：记录 `detail_id` + 错误，**不**改 space 为 active
- 重试 confirm：已对成功项有 `knowledge_doc_id` 的跳过或先 `DELETE …/documents/{doc_id}` 再 import
- 废止 space：Web 改 `status=superseded` 后，BFF 批量 **DELETE** 对应 knowledge documents（或检索侧按 `rule_space_id` 过滤 + 仅 `active` space）

**明细变更（active 后编辑 body）：**

- `PATCH rule_details` 后调 **`POST …/documents/{doc_id}/reindex`**（重新上传同 embed 文本）或 delete + import

### 5.3 法规检索

| 项 | 值 |
|----|-----|
| 方法 / 路径 | **`POST /api/knowledge/v1/search`** |
| 鉴权 | `knowledge:read` |

**请求示例：**

```json
{
  "query": "个人信息收集 consent",
  "spaces": ["{LEGAL_KNOWLEDGE_SPACE_ID}"],
  "kinds": ["legal-clause"],
  "tags": ["entertainment"],
  "top_k": 10
}
```

**Web 映射 Evidence → 审计：**

```typescript
// items[] 来自 EvidencePackResponse
{
  snippet: string;
  score: number;
  metadata: {
    detail_id: string;      // attrs 同步
    rule_space_id: string;
    segment_label: string;
    doc_id: string;         // knowledge document
  };
}
```

BFF 对外仍可提供 **`POST /search`**（法务 BFF），内部转发上述 knowledge search 并补全 `rule_details` 正文。

### 5.4 调用关系（confirm）

```text
浏览器 → POST /spaces/{id}/confirm
  → BFF 读 rule_details[]
  → 每条 POST /api/doc/embed/{ks}
  → 每条 PATCH …/documents/{doc_id}（attrs.detail_id …）
  → 全部 OK → rule_spaces.status=active, embedded_at=now()
```

### 5.5 DeerFlow 依赖一览

| 场景 | API |
|------|-----|
| 确认向量化 | `POST /api/doc/embed/{space_id}` |
| 写向量 metadata | `PATCH …/documents/{doc_id}` |
| 改条文 re-embed | `POST …/documents/{doc_id}/reindex` |
| 废止删向量 | `DELETE …/documents/{doc_id}` |
| 法规检索 | `POST /api/knowledge/v1/search` |

---

## 6. Web BFF API（自管）

### 6.1 法律库

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/spaces` | 上传编排：§4 调 doc/parse → 落库 draft |
| GET | `/spaces` | 主表列表 |
| GET/PATCH | `/spaces/{id}` | 主表 meta / status |
| GET/PATCH | `/spaces/{id}/details` | 明细 CRUD |
| POST | `/spaces/{id}/confirm` | 编排 §5.2 knowledge import → active |

### 6.2 法规检索

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/search` | 转发 DeerFlow `POST /api/knowledge/v1/search`（§5.3） |

### 6.3 规则树

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tree` | 整树 |
| GET | `/tree/checkpoints?industry_tags=` | 按行业筛检查点 |
| POST/PATCH/DELETE | `/tree/nodes`, `/tree/checkpoints` | CRUD |
| POST | `/tree/nodes/{id}/validate-weights` | 权重校验 |
| POST | `/tree/import` | P1 CSV 导入 |

### 6.4 码表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/pub_codes/bundle?domain=legal` | 表单聚合 |
| GET/POST/PATCH/DELETE | `/pub_codes/…` | CRUD |

---

## 7. 数据表

### 7.1 `rule_spaces`（主表）

| 字段 | 说明 |
|------|------|
| `id` | PK |
| `title` | 标题 |
| `category` | pub_codes · `space_category` |
| `status` | `draft` \| `active` \| `superseded` \| `archived` |
| `valid_from` / `valid_to` | 时效 |
| `tags[]` | 行业 · `industry_tag` |
| `attrs` | `embedded_at`, `segment_prompt`, `source_filename`, `knowledge_space_id`, … |
| `detail_count` | 明细条数 |
| `created_by` / timestamps | |

**版本**：禁止在原 space 覆盖明细；新版 = 重新上传 + 新 space；旧 space 只改 status。

### 7.2 `rule_details`（明细）

| 字段 | 说明 |
|------|------|
| `id` | PK；**向量 metadata.detail_id** |
| `space_id` | FK |
| `category` | 冗余 |
| `segment_label` | 条号 |
| `chapter_path` | 章节 |
| `body` | 正文 |
| `sort_key` | 排序 |
| `refs` | JSONB；`resolve_refs` 产出 |
| `attrs` | `knowledge_doc_id`（DeerFlow import 返回，confirm 后写入） |

### 7.3 `rule_tree_nodes`

| 字段 | 说明 |
|------|------|
| `id` | PK |
| `parent_id` | 一级为 null |
| `depth` | 1 \| 2 |
| `name` | 维度名 |
| `max_score` | 仅 depth=2 |
| `sort_key` | |

### 7.4 `rule_checkpoints`

| 字段 | 说明 |
|------|------|
| `id` | PK |
| `node_id` | FK → depth=2 节点 |
| `name` / `description` | |
| `industry_tags[]` | |
| `mandatory` / `score_type` | pub_codes |
| `weight` | 一票否决 = 0 |
| `legal_refs` | `[{ space_id, detail_id, label }]` |

Gateway/BFF 校验：权重和、一票否决、名称长度等。

### 7.5 `pub_codes`

| 字段 | 说明 |
|------|------|
| `domain` | `legal` 法务等 |
| `type_key` | `space_category`, `industry_tag`, … |
| `code` / `label` | 存库值 / 展示 |
| `attrs` | `type_name`, `multi_value`, … |

`UNIQUE(domain, type_key, code)`。

---

## 8. 数据模型（UI 绑定）

### 8.1 主表 `RuleSpace`

| 字段 | UI |
|------|-----|
| `id` | 路由参数 |
| `title` | 可编辑 |
| `category` | 下拉 · `space_category` |
| `status` | draft / active / … · `space_status` |
| `valid_from` / `valid_to` | 日期 |
| `tags[]` | 多选 · `industry_tag` |
| `detail_count` | 只读 |
| `attrs.embedded_at` | 确认后展示 |

### 8.2 明细 `RuleDetail`

| 字段 | UI |
|------|-----|
| `id` | **审计主键 detail_id** |
| `space_id` | 所属法律 |
| `segment_label` | 条号 |
| `chapter_path` | 章节 |
| `body` | 正文编辑器 |
| `refs` | 引用展示 |

### 8.3 检查点 `RuleCheckpoint`

| 字段 | UI |
|------|-----|
| `name` / `description` | 文本 |
| `industry_tags[]` | 多选 |
| `mandatory` / `score_type` | 下拉 · pub_codes |
| `weight` | 数字；一票否决=0 |
| `legal_refs[]` | `{ space_id, detail_id, label }` picker |

检查点满分（展示用）：`dimension.max_score × weight`。

### 8.4 检索 Evidence（审计）

```typescript
type RuleEvidence = {
  text: string;
  score: number;
  metadata: {
    rule_space_id: string;
    detail_id: string;
    segment_label: string;
    doc_id: string;
  };
};
```

**审计页逻辑**：

1. 查本地 `rule_details`（`detail_id`）→ 条文原文  
2. 查本地规则树 → 筛选 `legal_refs` 含该 `detail_id` 的检查点 → **权重 / 满分 / 评分类型**

---

## 9. 计分规则

数据来自 Web 规则树；**计分代码在 Web**（或 Web BFF）。

| 规则 | 说明 |
|------|------|
| 适用检查点 | PRD 行业 ∩ 检查点 `industry_tags` ≠ ∅，或检查点含 `general` |
| 满分基数 | 仅适用检查点：`Σ dimension.max_score`（例：general only=100；general+文娱=115） |
| 一级汇总 | 按一级维度 `parent_id` 汇总得分 |
| 一票否决 | 不满足法律依据时的封顶分（配置可在 Web） |
| 同检查点多 hit | 每处编号；是否满足 **综合** 判定，不按位置分别打分 |

---

## 10. 码表（`domain=legal`）

Web 表单与 BFF 校验共用同一套 `code`：

| `type_key` | 绑定 |
|------------|------|
| `space_category` | 上传 category |
| `space_status` | 主表 status |
| `industry_tag` | 主表 tags、检查点 industry_tags |
| `checkpoint_mandatory` | 检查点 mandatory |
| `checkpoint_score_type` | 检查点 score_type |

管理页：`/settings/codes?domain=legal`。

---

## 11. 飞书字段对照

[法律库文档表](https://sensetime.feishu.cn/wiki/Subjwt9Qhib3j0kKMLacAzn0nzb) → 主表；[法律条款库](https://sensetime.feishu.cn/wiki/TFEiwfC5PiYjXjkSKW0c3L3tnaf) → 明细；[规则树](https://sensetime.feishu.cn/wiki/BJVDwozGAiFY4ckJ6YLcwZqlnsd) → 规则树页。

关联评分检查点：仅在 **检查点 · legal_refs.detail_id**，明细表 **不存** 检查点 id。

L4 案例库、PRD 结论文案表：**Web 自有数据**（P2）。

---

## 12. 分期

| 阶段 | 内容 |
|------|------|
| **P0** | 法律库 + doc-parse + **confirm 调 knowledge import** + search + 规则树 + 码表 |
| **P1** | 飞书同步 UI、规则树 CSV 导入 |
| **P2** | PRD 自查全流程、审计高亮、计分报告 |

---

## 13. 制度预审（可选入口）

制度预审走 DeerFlow **Agent**（对话/thread），不是本 Web 的 REST 上传链路。  
产品若要在 Web 嵌入，复用 DeerFlow 前端或 iframe 对话组件，见 [`policy-review-design.md`](./policy-review-design.md)。

---

## 相关文档

- [`doc-parse-design.md`](./doc-parse-design.md) — DeerFlow 文档解析
- [`knowledge-design.md`](./knowledge-design.md) — DeerFlow 向量化与检索
- [`policy-review-design.md`](./policy-review-design.md)

飞书规格：[字段与规则](https://sensetime.feishu.cn/wiki/BJVDwozGAiFY4ckJ6YLcwZqlnsd?sheet=0a1768) · [法律库文档表](https://sensetime.feishu.cn/wiki/Subjwt9Qhib3j0kKMLacAzn0nzb) · [法律条款库](https://sensetime.feishu.cn/wiki/TFEiwfC5PiYjXjkSKW0c3L3tnaf)
