---
name: policy-review
description: >
  Use this skill instead of read_file/bash for ANY compliance or legal pre-review
  of an uploaded policy, contract, PRD, or business document. Immediately call
  policy_prepare (omit doc_path when a file is uploaded) — it parses docx/pdf/md
  via Docling and retrieves evidence. Do NOT read_file the review upload, convert
  docx yourself, or ask_clarification about encoding. Trigger on 制度预审、合规审查、
  条款审查、风险审核、法务预审, or policy/legal/ethics pre-checks.
---

# Policy Review

Machine compliance pre-review for business readers. Parse with `policy_prepare`,
draft findings from returned evidence, then `policy_finalize`. The server renders
the only user-visible outputs: a Chinese Markdown report and a JSON result file.

## Workflow

1. **Prepare** — Call `policy_prepare` right away (omit `doc_path` if a file is
   already uploaded). Docling handles docx / pdf / md; do not use `read_file`,
   bash, python-docx, or pandoc on the review document, and do not ask the user
   how to open binary formats.
2. **Draft** — From `draft_scaffold`, `evidence_digest`, `quote_pool`, and
   `allowed_ids`, fill all findings in one pass. Do **not** call `policy_retrieve`
   again after a successful `policy_prepare` (it already retrieved). If you must
   re-retrieve, pass the original prepare `sections` (`title`+`body`) — never pass
   `section_results`. Copy every `evidence.quote` **verbatim** from
   `quote_pool.quotes`. Cite only ids shown in `evidence_digest` for that section.
3. **Finalize** — Immediately call `policy_finalize` with **`draft` as a JSON
   string** (not a nested object)::

        {"summary":"...","findings":[{"risk":"high","text":"...","quote":"...","citation_ids":["id-from-digest"],"section":"...","suggestion":"..."}]}

   Do not write Markdown analysis to the user. If `retry=true`, fix only
   `validation.errors` using returned `quote_pool` / `evidence_digest`, then
   retry. After a successful finalize, **do not write any further message** —
   the server already delivered the business report and JSON.

If there is no review document yet, ask the user to upload one. Do not invent
document content.

## Rules

- User-facing output is **only** the server report (+ JSON artifact). Never explain
  schema fields, tool names, JSON parse errors, or retry history to the user.
- The document under review is not itself policy authority; cite only this turn's
  `evidence_digest` / `allowed_ids`.
- `evidence.quote` must be copied verbatim from the matching `quote_pool.quotes`.
- medium / high findings with non-low confidence must cite an id from
  `evidence_digest` for that section.
- high findings need a suggestion; provide `edit` when the text can be patched
  directly.
- Empty retrieval or weak evidence → do not invent violations; keep refusal and
  still call finalize.
- Fill findings on scaffold dimensions; keep empty `findings` on clean dimensions.
- Pass only `summary` and `dimensions` to finalize — never invent the final report.
