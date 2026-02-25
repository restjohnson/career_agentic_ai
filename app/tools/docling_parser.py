from __future__ import annotations

import os
import tempfile
from typing import Optional


def parse_document_to_markdown(file_bytes: bytes, suffix: str = ".pdf") -> str:
    """
    Parse a document (PDF, DOCX, etc.) using Docling and return its
    markdown representation. Docling is lazy-imported to avoid loading
    ML models at server startup.

    Args:
        file_bytes: Raw file content.
        suffix: File extension including the dot (e.g. ".pdf", ".docx").
                Used so Docling picks the right parser.

    Returns:
        Markdown string of the parsed document.
    """
    from docling.document_converter import DocumentConverter  # lazy import

    converter = DocumentConverter()

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        result = converter.convert(tmp_path)
        return result.document.export_to_markdown()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def infer_suffix(filename: Optional[str], content_type: Optional[str] = None) -> str:
    """
    Return the file extension to use when writing to a temp file.
    Falls back to .pdf if nothing useful can be determined.
    """
    if filename:
        _, ext = os.path.splitext(filename)
        if ext:
            return ext.lower()

    _MIME_MAP = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "text/html": ".html",
        "text/markdown": ".md",
        "text/plain": ".txt",
    }
    if content_type:
        return _MIME_MAP.get(content_type, ".pdf")

    return ".pdf"
