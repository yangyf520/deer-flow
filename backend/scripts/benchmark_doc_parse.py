#!/usr/bin/env python3
"""Benchmark doc_parse pipeline stages (parse → blocks → LLM batches)."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# repo root on path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "packages" / "harness"))
sys.path.insert(0, str(ROOT / "backend"))

from deerflow.config.app_config import get_app_config  # noqa: E402
from deerflow.doc_parse import pipeline  # noqa: E402
from deerflow.doc_parse.pipeline import parse_document  # noqa: E402


def _sample_legal_markdown(article_count: int) -> bytes:
    lines = ["# 示例管理办法", "", "**第一章**　总则", ""]
    for i in range(1, article_count + 1):
        lines.append(f"**第{i}条**　本条为第{i}条示例内容，用于测试文档解析批处理性能。")
        lines.append("")
    return "\n".join(lines).encode()


async def _bench(article_count: int) -> None:
    app_config = get_app_config()
    data = _sample_legal_markdown(article_count)
    prompt = '你是法规文档切条助手。只输出 JSON：{"title":"…","details":[{"segment_label":"第N条","chapter_path":"第一章 总则","body":"原文","ref_labels":[]}]} body 必须与原文逐字一致。'

    t0 = time.perf_counter()
    parsed, backend = await asyncio.to_thread(pipeline._to_markdown, data, "sample.md")
    t_parse = time.perf_counter()

    blocks = pipeline._markdown_blocks(parsed.text or "")
    t_blocks = time.perf_counter()

    limits = pipeline.resolve_parse_batch_limits(app_config=app_config, model_name="default")
    batches = pipeline._batches(blocks, max_chars=limits.max_chars, max_blocks=limits.max_blocks)
    t_pack = time.perf_counter()

    print(f"\n=== articles={article_count} backend={backend} ===")
    print(f"  parse:   {(t_parse - t0) * 1000:.0f} ms")
    print(f"  blocks:  {(t_blocks - t_parse) * 1000:.0f} ms  ({len(blocks)} blocks)")
    print(f"  pack:    {(t_pack - t_blocks) * 1000:.0f} ms  ({len(batches)} batches, max_chars={limits.max_chars})")

    t_llm0 = time.perf_counter()
    result = await parse_document(
        data=data,
        filename="sample.md",
        segment_prompt=prompt,
        app_config=app_config,
        model_name="default",
    )
    t_llm1 = time.perf_counter()

    print(f"  llm+merge: {(t_llm1 - t_llm0) * 1000:.0f} ms")
    print(f"  total:   {(t_llm1 - t0) * 1000:.0f} ms")
    meta = result.meta
    print(f"  meta:    parse_ms={meta.parse_ms} block_ms={meta.block_ms} llm_ms={meta.llm_ms} total_ms={meta.total_ms} batches={meta.batch_count}")
    print(f"  details: {len(result.data.get('details') or [])}  warnings: {len(result.meta.warnings)}")


async def main() -> None:
    for n in (10, 30, 50):
        await _bench(n)


if __name__ == "__main__":
    asyncio.run(main())
