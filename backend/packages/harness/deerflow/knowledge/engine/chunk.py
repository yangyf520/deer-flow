"""Document chunking strategy and LlamaIndex transforms."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.knowledge.engine.evidence import (
    MD_HEADING_RE,
    MD_TABLE_RE,
    annotate_block_type,
    instantiate_class,
    node_text,
)
from deerflow.utils.file_conversion import sanitize_media


def ContextualTitleTransform():
    """Prefix document title before embedding."""
    from llama_index.core.schema import TransformComponent

    class _ContextualTitleTransform(TransformComponent):
        def __call__(self, nodes: Sequence[Any], **kwargs: Any) -> Sequence[Any]:
            for node in nodes:
                meta = dict(getattr(node, "metadata", None) or {})
                title = meta.get("title") or ""
                text = node.get_content() if hasattr(node, "get_content") else getattr(node, "text", "")
                text_s = str(text or "")
                if title and text_s and not text_s.startswith(f"《{title}》"):
                    if hasattr(node, "set_content"):
                        node.set_content(f"《{title}》\n{text_s}")
                    else:
                        node.text = f"《{title}》\n{text_s}"
            return nodes

    return _ContextualTitleTransform()


def MediaSanitizeTransform():
    """LlamaIndex TransformComponent: strip data-URI / base64 media from node text."""
    from llama_index.core.schema import TransformComponent

    class _MediaSanitizeTransform(TransformComponent):
        def __call__(self, nodes: Sequence[Any], **kwargs: Any) -> Sequence[Any]:
            for node in nodes:
                text = node_text(node)
                cleaned = sanitize_media(text)
                if cleaned != text:
                    if hasattr(node, "set_content"):
                        node.set_content(cleaned)
                    else:
                        node.text = cleaned
            return nodes

    return _MediaSanitizeTransform()


def BlockAnnotateTransform():
    """LlamaIndex TransformComponent: set metadata.block from content shape."""
    from llama_index.core.schema import TransformComponent

    class _BlockAnnotateTransform(TransformComponent):
        def __call__(self, nodes: Sequence[Any], **kwargs: Any) -> Sequence[Any]:
            for node in nodes:
                meta = dict(getattr(node, "metadata", None) or {})
                if not meta.get("block"):
                    meta["block"] = annotate_block_type(node_text(node))
                    node.metadata = meta
                if not meta.get("heading_path"):
                    m = MD_HEADING_RE.search(node_text(node))
                    if m:
                        line = node_text(node)[m.start() :].split("\n", 1)[0]
                        heading = re.sub(r"^#{1,6}\s*", "", line).strip()
                        if heading:
                            meta["heading_path"] = heading[:200]
                            node.metadata = meta
            return nodes

    return _BlockAnnotateTransform()


def looks_like_markdown(docs: Sequence[Any]) -> bool:
    sample = "\n".join((getattr(d, "text", "") or "")[:4000] for d in docs[:3])
    return bool(MD_HEADING_RE.search(sample) or MD_TABLE_RE.search(sample))


def build_node_parser(docs: Sequence[Any]):
    """Assemble LlamaIndex node parser from ingest strategy and document shape."""
    from llama_index.core.node_parser import HierarchicalNodeParser, MarkdownNodeParser

    ingest_cfg = get_knowledge_config().ingest
    strategy = (ingest_cfg.strategy or "auto").strip().lower()
    chunk_sizes = list(ingest_cfg.chunk_sizes or [1024, 256])
    overlap = int(ingest_cfg.chunk_overlap or 64)

    if (ingest_cfg.node_parser_use or "").strip():
        return instantiate_class_node_parser(ingest_cfg, chunk_sizes, overlap)

    if strategy == "markdown" or (strategy == "auto" and looks_like_markdown(docs)):
        return MarkdownNodeParser()

    if strategy == "hierarchical" or strategy == "auto":
        return HierarchicalNodeParser.from_defaults(chunk_sizes=chunk_sizes, chunk_overlap=overlap)

    return HierarchicalNodeParser.from_defaults(chunk_sizes=chunk_sizes, chunk_overlap=overlap)


def instantiate_class_node_parser(ingest_cfg, chunk_sizes: list[int], overlap: int):
    parser_kwargs = {
        k: v
        for k, v in ingest_cfg.model_dump(
            exclude={
                "node_parser_use",
                "chunk_sizes",
                "chunk_overlap",
                "strategy",
                "title_prefix",
                "transforms",
                "media_sanitize",
                "annotate_block",
            }
        ).items()
        if v is not None and v != ""
    }
    parser_kwargs.setdefault("chunk_sizes", chunk_sizes)
    parser_kwargs.setdefault("chunk_overlap", overlap)
    if len(chunk_sizes) == 1:
        parser_kwargs.setdefault("chunk_size", chunk_sizes[0])
    use = ingest_cfg.node_parser_use.strip()
    try:
        return instantiate_class(use, parser_kwargs)
    except TypeError:
        parser_kwargs.pop("chunk_sizes", None)
        return instantiate_class(use, parser_kwargs)


def build_ingest_transforms(docs: Sequence[Any]) -> list[Any]:
    """IngestionPipeline transforms: LI node parser + media/block + optional + title prefix."""
    ingest_cfg = get_knowledge_config().ingest
    transforms: list[Any] = [build_node_parser(docs)]
    if ingest_cfg.media_sanitize:
        transforms.append(MediaSanitizeTransform())
    if ingest_cfg.annotate_block:
        transforms.append(BlockAnnotateTransform())
    for tcfg in ingest_cfg.transforms or []:
        use = (tcfg.use or "").strip()
        if not use:
            continue
        kwargs = tcfg.model_dump(exclude={"use"}, exclude_none=True)
        transforms.append(instantiate_class(use, kwargs))
    if ingest_cfg.title_prefix:
        transforms.append(ContextualTitleTransform())
    return transforms
