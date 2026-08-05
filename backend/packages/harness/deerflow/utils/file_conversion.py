"""File conversion and document parsing utilities.

Two intentional paths (do not merge casually):

- **Upload sidecar** (chat outline): PDF/Office → ``.md`` via pymupdf4llm /
  MarkItDown. Always available; outline heuristics are tuned for that output.
- **Runtime / knowledge / policy**: bytes → Markdown via Docling
  (``parse_file_bytes`` / ``DocumentStream``). Used by ``read_file``,
  knowledge ingest, and ``policy_prepare``.

Large upload files (> ASYNC_THRESHOLD_BYTES) convert in a thread pool via
asyncio.to_thread() to avoid blocking the event loop (fixes #1569).

No FastAPI or HTTP dependencies — pure utility functions.
"""

import asyncio
import logging
import re
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from deerflow.config.app_config import get_app_config

logger = logging.getLogger(__name__)

_docling_converter: Any | None = None
_docling_converter_lock = threading.Lock()
_markitdown_instance: Any | None = None
_markitdown_lock = threading.Lock()

DATA_URI = re.compile(
    r"data:(?:image|application)/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]{64,}",
    re.IGNORECASE,
)


@dataclass
class ParseResult:
    text: str
    parse_quality: str
    error: str | None = None


def sanitize_media(text: str) -> str:
    """Remove embedded media payloads while preserving readable Markdown."""
    if not text:
        return ""
    cleaned = DATA_URI.sub("[image]", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _get_docling_converter() -> Any:
    """Reuse one ``DocumentConverter`` — cold start loads layout/OCR models once."""
    global _docling_converter
    if _docling_converter is not None:
        return _docling_converter
    with _docling_converter_lock:
        if _docling_converter is None:
            from docling.document_converter import DocumentConverter

            _docling_converter = DocumentConverter()
        return _docling_converter


def _get_markitdown() -> Any:
    global _markitdown_instance
    if _markitdown_instance is not None:
        return _markitdown_instance
    with _markitdown_lock:
        if _markitdown_instance is None:
            from markitdown import MarkItDown

            _markitdown_instance = MarkItDown()
        return _markitdown_instance


def parse_docling(source: Any) -> ParseResult:
    """Convert via Docling ``DocumentConverter`` (path, URL, or DocumentStream)."""
    try:
        from docling.document_converter import DocumentConverter  # noqa: F401
    except ImportError:
        return ParseResult(text="", parse_quality="failed", error="Docling is not installed")

    try:
        text = sanitize_media(_get_docling_converter().convert(source).document.export_to_markdown())
        if not text:
            return ParseResult(text="", parse_quality="failed", error="empty Docling output")
        return ParseResult(text=text, parse_quality="ok")
    except Exception as exc:
        logger.warning("Docling parse failed: %s", exc)
        return ParseResult(text="", parse_quality="failed", error=str(exc))


def parse_markitdown_bytes(data: bytes, filename: str) -> ParseResult:
    """Parse document bytes via MarkItDown (fallback when Docling is unavailable)."""
    import tempfile

    try:
        from markitdown import MarkItDown  # noqa: F401
    except ImportError:
        return ParseResult(text="", parse_quality="failed", error="MarkItDown is not installed")

    suffix = Path(filename).suffix or ".bin"
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            path = Path(tmp.name)
        text = (_get_markitdown().convert(str(path)).text_content or "").strip()
        if not text:
            return ParseResult(text="", parse_quality="failed", error="empty MarkItDown output")
        return ParseResult(text=text, parse_quality="ok")
    except Exception as exc:
        logger.warning("MarkItDown parse failed for %s: %s", filename, exc)
        return ParseResult(text="", parse_quality="failed", error=str(exc))
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def parse_file_bytes_with_fallback(data: bytes, filename: str) -> tuple[ParseResult, str]:
    """Parse bytes via Docling, falling back to MarkItDown when Docling is missing or fails."""
    parsed = parse_file_bytes(data, filename)
    if parsed.parse_quality == "ok" and (parsed.text or "").strip():
        return parsed, "docling"
    logger.info(
        "Docling unavailable for %s (%s); falling back to MarkItDown",
        filename,
        parsed.error,
    )
    return parse_markitdown_bytes(data, filename), "markitdown"


def parse_file_bytes(data: bytes, filename: str) -> ParseResult:
    """Parse document bytes via Docling ``DocumentStream`` (no temp file)."""
    try:
        from docling.datamodel.base_models import DocumentStream
    except ImportError:
        return ParseResult(text="", parse_quality="failed", error="Docling is not installed")

    stream = DocumentStream(name=Path(filename).name or "document.bin", stream=BytesIO(data))
    return parse_docling(stream)


# File extensions that should be converted to markdown
CONVERTIBLE_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}

# Files larger than this threshold are converted in a background thread.
# Small files complete in < 1s synchronously; spawning a thread adds unnecessary
# scheduling overhead for them.
_ASYNC_THRESHOLD_BYTES = 1 * 1024 * 1024  # 1 MB

# If pymupdf4llm produces fewer characters *per page* than this threshold,
# the PDF is likely image-based or encrypted — fall back to MarkItDown.
# Rationale: normal text PDFs yield 200-2000 chars/page; image-based PDFs
# yield close to 0. 50 chars/page gives a wide safety margin.
# Falls back to absolute 200-char check when page count is unavailable.
_MIN_CHARS_PER_PAGE = 50


def _pymupdf_output_too_sparse(text: str, file_path: Path) -> bool:
    """Return True if pymupdf4llm output is suspiciously short (image-based PDF).

    Uses chars-per-page rather than an absolute threshold so that both short
    documents (few pages, few chars) and long documents (many pages, many chars)
    are handled correctly.
    """
    chars = len(text.strip())
    doc = None
    pages: int | None = None
    try:
        import pymupdf

        doc = pymupdf.open(str(file_path))
        pages = len(doc)
    except Exception:
        pass
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
    if pages is not None and pages > 0:
        return (chars / pages) < _MIN_CHARS_PER_PAGE
    # Fallback: absolute threshold when page count is unavailable
    return chars < 200


def _convert_pdf_with_pymupdf4llm(file_path: Path) -> str | None:
    """Attempt PDF conversion with pymupdf4llm.

    Returns the markdown text, or None if pymupdf4llm is not installed or
    if conversion fails (e.g. encrypted/corrupt PDF).
    """
    try:
        import pymupdf4llm
    except ImportError:
        return None

    try:
        return pymupdf4llm.to_markdown(str(file_path))
    except Exception:
        logger.exception("pymupdf4llm failed to convert %s; falling back to MarkItDown", file_path.name)
        return None


def _convert_with_markitdown(file_path: Path) -> str:
    """Convert any supported file to markdown text using MarkItDown."""
    from markitdown import MarkItDown

    md = MarkItDown()
    return md.convert(str(file_path)).text_content


def _do_convert(file_path: Path, pdf_converter: str) -> str:
    """Synchronous conversion — called directly or via asyncio.to_thread.

    Args:
        file_path: Path to the file.
        pdf_converter: "auto" | "pymupdf4llm" | "markitdown"
    """
    is_pdf = file_path.suffix.lower() == ".pdf"

    if is_pdf and pdf_converter != "markitdown":
        # Try pymupdf4llm first (auto or explicit)
        pymupdf_text = _convert_pdf_with_pymupdf4llm(file_path)

        if pymupdf_text is not None:
            # pymupdf4llm is installed
            if pdf_converter == "pymupdf4llm":
                # Explicit — use as-is regardless of output length
                return pymupdf_text
            # auto mode: fall back if output looks like a failed parse.
            # Use chars-per-page to distinguish image-based PDFs (near 0) from
            # legitimately short documents.
            if not _pymupdf_output_too_sparse(pymupdf_text, file_path):
                return pymupdf_text
            logger.warning(
                "pymupdf4llm produced only %d chars for %s (likely image-based PDF); falling back to MarkItDown",
                len(pymupdf_text.strip()),
                file_path.name,
            )
        # pymupdf4llm not installed or fallback triggered → use MarkItDown

    return _convert_with_markitdown(file_path)


async def convert_file_to_markdown(file_path: Path, output_path: Path | None = None) -> Path | None:
    """Convert a supported document file to Markdown.

    PDF files are handled with a two-converter strategy (see module docstring).
    Large files (> 1 MB) are offloaded to a thread pool to avoid blocking the
    event loop.

    Args:
        file_path: Path to the file to convert.
        output_path: Optional destination for the generated ``.md`` file.
            When omitted, writes to ``file_path`` with a ``.md`` suffix.
            Callers that track per-request filename uniqueness should pass a
            pre-claimed path so companion markdown cannot clobber other uploads.

    Returns:
        Path to the generated .md file, or None if conversion failed.
    """
    try:
        pdf_converter = _get_pdf_converter()
        file_size = file_path.stat().st_size

        if file_size > _ASYNC_THRESHOLD_BYTES:
            text = await asyncio.to_thread(_do_convert, file_path, pdf_converter)
        else:
            text = _do_convert(file_path, pdf_converter)

        md_path = output_path if output_path is not None else file_path.with_suffix(".md")
        md_path.write_text(text, encoding="utf-8")

        logger.info("Converted %s to markdown: %s (%d chars)", file_path.name, md_path.name, len(text))
        return md_path
    except Exception as e:
        logger.error("Failed to convert %s to markdown: %s", file_path.name, e)
        return None


# Regex for bold-only lines that look like section headings.
# Targets SEC filing structural headings that pymupdf4llm renders as **bold**
# rather than # Markdown headings (because they use same font size as body text,
# distinguished only by bold+caps formatting).
#
# Pattern requires ALL of:
#   1. Entire line is a single **...** block (no surrounding prose)
#   2. Starts with a recognised structural keyword:
#      - ITEM / PART / SECTION (with optional number/letter after)
#      - SCHEDULE, EXHIBIT, APPENDIX, ANNEX, CHAPTER
#      All-caps addresses, boilerplate ("CURRENT REPORT", "SIGNATURES",
#      "WASHINGTON, DC 20549") do NOT start with these keywords and are excluded.
#
# Chinese headings (第三节...) are already captured as standard # headings
# by pymupdf4llm, so they don't need this pattern.
_BOLD_HEADING_RE = re.compile(r"^\*\*((ITEM|PART|SECTION|SCHEDULE|EXHIBIT|APPENDIX|ANNEX|CHAPTER)\b[A-Z0-9 .,\-]*)\*\*\s*$")

# Regex for split-bold headings produced by pymupdf4llm when a heading spans
# multiple text spans in the PDF (e.g. section number and title are separate spans).
# Matches lines like:  **1** **Introduction**  or  **3.2** **Multi-Head Attention**
# Requirements:
#   1. Entire line consists only of **...** blocks separated by whitespace (no prose)
#   2. First block is a section number (digits and dots, e.g. "1", "3.2", "A.1")
#   3. Second block must not be purely numeric/punctuation — excludes financial table
#      headers like **2023** **2022** **2021** while allowing non-ASCII titles such as
#      **1** **概述** or accented words (negative lookahead instead of [A-Za-z])
#   4. At most two additional blocks (four total) with [^*]+ (no * inside) to keep
#      the regex linear and avoid ReDoS on attacker-controlled content
_SPLIT_BOLD_HEADING_RE = re.compile(r"^\*\*[\dA-Z][\d\.]*\*\*\s+\*\*(?!\d[\d\s.,\-–—/:()%]*\*\*)[^*]+\*\*(?:\s+\*\*[^*]+\*\*){0,2}\s*$")

# Maximum number of outline entries injected into the agent context.
# Keeps prompt size bounded even for very long documents.
MAX_OUTLINE_ENTRIES = 50

_ALLOWED_PDF_CONVERTERS = {"auto", "pymupdf4llm", "markitdown"}


def _clean_bold_title(raw: str) -> str:
    """Normalise a title string that may contain pymupdf4llm bold artefacts.

    pymupdf4llm sometimes emits adjacent bold spans as ``**A** **B**`` instead
    of a single ``**A B**`` block.  This helper merges those fragments and then
    strips the outermost ``**...**`` wrapper so the caller gets plain text.

    Examples::

        "**Overview**"                       → "Overview"
        "**UNITED STATES** **SECURITIES**"   → "UNITED STATES SECURITIES"
        "plain text"                         → "plain text"  (unchanged)
    """
    # Merge adjacent bold spans: "** **" → " "
    merged = re.sub(r"\*\*\s*\*\*", " ", raw).strip()
    # Strip outermost **...** if the whole string is wrapped
    if m := re.fullmatch(r"\*\*(.+?)\*\*", merged, re.DOTALL):
        return m.group(1).strip()
    return merged


def extract_outline(md_path: Path) -> list[dict]:
    """Extract document outline (headings) from a Markdown file.

    Recognises three heading styles produced by pymupdf4llm:

    1. Standard Markdown headings: lines starting with one or more '#'.
       Inline ``**...**`` wrappers and adjacent bold spans (``** **``) are
       cleaned so the title is plain text.

    2. Bold-only structural headings: ``**ITEM 1. BUSINESS**``, ``**PART II**``,
       etc.  SEC filings use bold+caps for section headings with the same font
       size as body text, so pymupdf4llm cannot promote them to # headings.

    3. Split-bold headings: ``**1** **Introduction**``, ``**3.2** **Attention**``.
       pymupdf4llm emits these when the section number and title text are
       separate spans in the underlying PDF (common in academic papers).

    Args:
        md_path: Path to the .md file.

    Returns:
        List of dicts with keys: title (str), line (int, 1-based).
        When the outline is truncated at MAX_OUTLINE_ENTRIES, a sentinel entry
        ``{"truncated": True}`` is appended as the last element so callers can
        render a "showing first N headings" hint without re-scanning the file.
        Returns an empty list if the file cannot be read or has no headings.
    """
    outline: list[dict] = []
    try:
        with md_path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                # Style 1: standard Markdown heading
                if stripped.startswith("#"):
                    title = _clean_bold_title(stripped.lstrip("#").strip())
                    if title:
                        outline.append({"title": title, "line": lineno})

                # Style 2: single bold block with SEC structural keyword
                elif m := _BOLD_HEADING_RE.match(stripped):
                    title = m.group(1).strip()
                    if title:
                        outline.append({"title": title, "line": lineno})

                # Style 3: split-bold heading — **<num>** **<title>**
                # Regex already enforces max 4 blocks and non-numeric second block.
                elif _SPLIT_BOLD_HEADING_RE.match(stripped):
                    title = " ".join(re.findall(r"\*\*([^*]+)\*\*", stripped))
                    if title:
                        outline.append({"title": title, "line": lineno})

                if len(outline) > MAX_OUTLINE_ENTRIES:
                    # We collected one heading beyond the limit, which proves the
                    # document genuinely has more than MAX_OUTLINE_ENTRIES headings.
                    # Drop that extra entry and append the truncation sentinel.
                    outline.pop()
                    outline.append({"truncated": True})
                    break
    except Exception:
        return []

    return outline


def _get_uploads_config_value(key: str, default: object) -> object:
    """Read a value from the uploads config, supporting dict and attribute access."""
    cfg = get_app_config()
    uploads_cfg = getattr(cfg, "uploads", None)
    if isinstance(uploads_cfg, dict):
        return uploads_cfg.get(key, default)
    return getattr(uploads_cfg, key, default)


def _get_pdf_converter() -> str:
    """Read pdf_converter setting from app config, defaulting to 'auto'.

    Normalizes the value to lowercase and validates it against the allowed set
    so that values like 'AUTO' or 'MarkItDown' from config.yaml don't silently
    fall through to unexpected behaviour.
    """
    try:
        raw = str(_get_uploads_config_value("pdf_converter", "auto")).strip().lower()
        if raw not in _ALLOWED_PDF_CONVERTERS:
            logger.warning("Invalid pdf_converter value %r; falling back to 'auto'", raw)
            return "auto"
        return raw
    except Exception:
        pass
    return "auto"
