# 文档解析 · DeerFlow 设计

> **读者**：DeerFlow 后端。  
> **范围**：上传文件 + `segment_prompt` → JSON；无业务表、无固定业务字段。  
> **调用方**：[`policy-rule-web-design.md`](./policy-rule-web-design.md) §4。

---

## 1. 流水线

```text
POST /api/doc/parse（multipart: file + segment_prompt）
  → parse_file_bytes（Docling；失败则 MarkItDown fallback）
  → MarkdownNodeParser 分块；若仅 1 块 → ATX # 或行首 **bold** 标题切分
  → 打包 batch（≤4000 字、≤10 段/批）→ 并行 run_oneshot_llm（≤4 并发）
  → langchain parse_json_markdown → 数组合并
  → grounding + 质量 warnings
  → { data, meta }（不写库）
```

固定 pipeline，**不走 Agent / Skill / knowledge import**。

### 1.1 物理切块（代码）

| 步骤 | 说明 |
|------|------|
| 解析 | Docling 优先；不可用（缺 torch 等）→ MarkItDown |
| 结构切分 | LlamaIndex `MarkdownNodeParser`；单块时 fallback：`^#{1,6}\s` 或行首 `**标题**` |
| 超限块 | 单段 >4000 字 → 按 `\n\n` 段落边界硬切 |
| LLM 批次 | 贪心打包：每批 ≤4000 字且 ≤10 个 section |

### 1.2 语义切条（调用方）

`segment_prompt` 必填，定义 JSON 形状与切条规则；平台无内置业务 prompt。

### 1.3 质量检查（代码）

合并后对 `details[]` 检查：

- 空 `body`
- 重复 `segment_label`
- **grounding**：规范化空白后，`body`（或足够长前缀）须为源 Markdown 子串；否则 warning「possible paraphrase」

---

## 2. API

`APIRouter(prefix="/api/doc")` → **`POST /api/doc/parse`**  
鉴权：`runs:create`（同 input-polish）。

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
| 分块 | LlamaIndex `MarkdownNodeParser` + 通用标题 regex |
| LLM | `deerflow.utils.oneshot_llm.run_oneshot_llm`（`asyncio.gather`，`MAX_CONCURRENT_BATCHES=4`） |
| JSON | `langchain_core.utils.json.parse_json_markdown` + `strip_think_blocks` |
| Schema | 可选 `jsonschema` |
| 代码 | `deerflow/doc_parse/pipeline.py`、`app/gateway/routers/doc.py` |

多批 merge：同名 **list concat**，标量取首个非空。

### 3.1 Docling / torch

Docling 随 `deerflow-harness[knowledge]` extra 安装；`knowledge` extra 含 `torch` / `torchvision`（平台约束见 `backend/pyproject.toml` `[tool.uv]`）。

- Linux x86_64：`torch+cpu` 由 uv lock 解析（pytorch-cpu index）。
- **macOS 本地**：若 `import torch` 失败、Docling 回退 MarkItDown，在 `backend/` 执行：

```bash
make ensure-docling
# 或: bash scripts/ensure_docling_torch.sh
```

本地 `make dev` 在 `config.yaml → knowledge.enabled: true` 时会 `uv sync --extra knowledge`。

---

## 相关文档

- [`policy-rule-web-design.md`](./policy-rule-web-design.md) §4
