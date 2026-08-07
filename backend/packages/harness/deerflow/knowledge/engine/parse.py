"""Upload parsing via Docling/MarkItDown."""

from __future__ import annotations

import asyncio

from deerflow.config.knowledge_config import get_knowledge_config
from deerflow.utils.file_conversion import ParseResult, parse_file_bytes_with_fallback


async def parse_upload_bytes(data: bytes, filename: str) -> ParseResult:
    """Parse uploaded bytes with optional ``knowledge.parse.timeout_seconds``."""
    timeout = get_knowledge_config().parse.timeout_seconds

    def _parse() -> ParseResult:
        parsed, _backend = parse_file_bytes_with_fallback(data, filename)
        return parsed

    coro = asyncio.to_thread(_parse)
    if timeout and timeout > 0:
        try:
            return await asyncio.wait_for(coro, timeout=float(timeout))
        except TimeoutError:
            return ParseResult(
                text="",
                parse_quality="failed",
                error=f"parse timed out after {timeout}s",
            )
    return await coro
