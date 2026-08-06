# 文档解析 · DeerFlow 设计

> **读者**：DeerFlow 后端。  
> **范围**：上传文件 + `segment_prompt` → JSON；无业务表、无固定业务字段。  
> **调用方**：[`policy-rule-web-design.md`](./policy-rule-web-design.md) §4。

---

## 1. 流水线

```text
POST /api/document/parse（multipart: file + segment_prompt）
  → parse_file_bytes（Docling；失败则 MarkItDown fallback）
  → Markdown 分块：ATX `#` 标题、行首 `**bold**`、或 segment_prompt JSON 示例中的 segment_label 模式
  → 打包 batch（字符/段数预算由 parse 模型 ``max_tokens`` 推导）→ 并行 run_oneshot_llm（≤8 并发）
  → langchain parse_json_markdown → 数组合并
  → 为每条 detail 分配 UUID ``row_no``
  → grounding + 质量 warnings（空 body、重复 label、疑似 paraphrase）
  → { data, meta }（不写库）
```

固定 pipeline，**不走 Agent / Skill / knowledge import**。

### 1.1 物理切块（代码）

| 步骤 | 说明 |
|------|------|
| 解析 | Docling 优先；不可用（缺 torch 等）→ MarkItDown |
| 结构切分 | ATX `^#{1,6}\s`、行首 `**标题**`、或 segment_prompt JSON 示例中的 `segment_label` 模式 |
| 超限块 | 单段超过字符预算 → 按 `\n\n` 段落边界硬切 |
| LLM 批次 | 贪心打包：字符预算由 parse 模型 ``max_tokens`` 推导；每批段数 ``min(20, max(12, max_tokens // 1365))``；≤12 段且 ≤8k 字符的短文档单批发送 |

### 1.2 语义切条（调用方）

`segment_prompt` 必填，定义 JSON 形状与切条规则；平台无内置业务 prompt。

### 1.3 质量检查（代码）

合并后对 `details[]` 检查：

- 空 `body`
- 重复 `segment_label`
- **grounding**：NFKC + 空白规范化后，`body`（或足够长前缀）须为源 Markdown 子串；否则 warning「possible paraphrase」（不回填 body、不修正 chapter_path）。
- **`row_no`**：服务端为每条 detail 分配全局唯一 UUID；调用方预置的非空字符串 id 保留，整数或纯数字字符串（旧版行号）会被替换。

---

## 2. API

`APIRouter(prefix="/api/document")` → **`POST /api/document/parse`**  
鉴权：`runs:create`（同 input-polish）。

**向量化入库：** **`POST /api/knowledge/spaces/{space_id}/documents`**  
鉴权：`knowledge:write`。multipart：`file`、`kind`、可选 `title`、`tags[]`、`attrs`（JSON）、`segments`（JSON 预切块，含行号等 metadata）。结构化上传流程：parse → 预览 → import。

| 字段 | 必填 | 说明 |
|------|------|------|
| `file` | 是 | 待解析文件 |
| `segment_prompt` | 是 | 切条指令 + 输出 JSON 形状 |
| `output_schema` | 否 | JSON Schema；校验合并后的 `data` |

**响应 `meta`：**

| 字段 | 说明 |
|------|------|
| `source_filename` | 原始文件名 |
| `segment_prompt_hash` | prompt 摘要 |
| `block_count` | section 数（切块后） |
| `batch_count` | LLM 批次数 |
| `parse_quality` | `ok` / `failed`（解析阶段） |
| `parse_backend` | `docling` 或 `markitdown` |
| `warnings` | 质量提示（空 body、重复 label、grounding 失败等） |

---

## 3. 实现

| 步骤 | 复用 / 位置 |
|------|-------------|
| 解析 | `deerflow.utils.file_conversion.parse_file_bytes` + MarkItDown fallback |
| 分块 | 通用 Markdown 标题 regex + `prompt_hints.split_patterns` |
| LLM | `deerflow.utils.oneshot_llm.run_oneshot_llm`（`asyncio.gather`；batch 上限见模型 `max_tokens`） |
| JSON | `langchain_core.utils.json.parse_json_markdown` + `strip_think_blocks` |
| Schema | 可选 `jsonschema` |
| 代码 | `deerflow/doc_parse/pipeline.py`、`app/gateway/routers/doc.py` |

多批 merge：同名 **list concat**，标量取首个非空。

### 3.1 Docling / torch

Docling 随 `deerflow-harness[knowledge]` extra 安装；`knowledge` extra 含 `torch` / `torchvision`（平台约束见 `backend/pyproject.toml` `[tool.uv]`）。

- Linux x86_64：`torch+cpu` 由 uv lock 解析（pytorch-cpu index），`uv sync --extra knowledge` 即可。
- **macOS 本地**：lockfile 仅含 Linux torch wheel，`uv sync --extra knowledge` 装不上 torch；解析自动回退 **MarkItDown**（见 `parse_file_bytes_with_fallback`）。若需 Docling 高质量解析，可手动安装 PyPI torch（须在项目目录外执行，否则 uv 只 audit 不安装）：

```bash
(cd /tmp && uv pip install --python /path/to/backend/.venv/bin/python \
  --index-url https://pypi.org/simple "torch>=2.2.2,<2.3.0" "torchvision>=0.17.2,<0.18.0")
```

本地 `make dev` 在 `config.yaml → knowledge.enabled: true` 时会 `uv sync --extra knowledge`。

---

## 相关文档

- [`policy-rule-web-design.md`](./policy-rule-web-design.md) §4
