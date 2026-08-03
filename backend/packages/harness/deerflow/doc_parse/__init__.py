"""Generic document parse: file + prompt → structured JSON (no business persistence)."""

from deerflow.doc_parse.contract import DocParseMeta, DocParseResponse
from deerflow.doc_parse.pipeline import parse_document

__all__ = [
    "DocParseMeta",
    "DocParseResponse",
    "parse_document",
]
