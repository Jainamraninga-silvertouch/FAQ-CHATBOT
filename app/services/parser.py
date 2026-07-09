"""
Parser service: turns raw uploaded bytes (PDF / DOCX / TXT / XLSX) into plain text.

This is intentionally the ONLY module that knows about file formats. Every
other service works with plain Python strings, so adding a new file type
later (e.g. .pptx) only means adding a branch here.
"""
from __future__ import annotations

import io
import logging
from enum import Enum

import fitz  # PyMuPDF
import docx  # python-docx
import pandas as pd

logger = logging.getLogger(__name__)


class SupportedFileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    XLSX = "xlsx"
    XLS = "xls"


class UnsupportedFileTypeError(Exception):
    """Raised when a file extension isn't one we know how to parse."""


def detect_file_type(filename: str) -> SupportedFileType:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        return SupportedFileType(ext)
    except ValueError as exc:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '.{ext}'. Supported types: pdf, docx, txt, xlsx, xls."
        ) from exc


def extract_text(file_bytes: bytes, filename: str) -> str:
    """
    Extract raw text from a file's bytes based on its extension.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename: Original filename (used to determine file type).

    Returns:
        Extracted plain text (paragraph breaks preserved with "\n\n").
    """
    file_type = detect_file_type(filename)

    if file_type == SupportedFileType.PDF:
        return _extract_pdf(file_bytes)
    if file_type == SupportedFileType.DOCX:
        return _extract_docx(file_bytes)
    if file_type == SupportedFileType.TXT:
        return _extract_txt(file_bytes)
    if file_type in (SupportedFileType.XLSX, SupportedFileType.XLS):
        return _extract_excel(file_bytes)

    # Should be unreachable due to detect_file_type's validation.
    raise UnsupportedFileTypeError(filename)


def _extract_pdf(file_bytes: bytes) -> str:
    text_parts: list[str] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        for page in pdf:
            page_text = page.get_text("text").strip()
            if page_text:
                text_parts.append(page_text)
    logger.info("Extracted %d page(s) of text from PDF", len(text_parts))
    return "\n\n".join(text_parts)


def _extract_docx(file_bytes: bytes) -> str:
    document = docx.Document(io.BytesIO(file_bytes))
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    logger.info("Extracted %d paragraph(s) of text from DOCX", len(paragraphs))
    return "\n\n".join(paragraphs)


def _extract_txt(file_bytes: bytes) -> str:
    # Try a couple of common encodings before giving up.
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode text file with common encodings.")


def _extract_excel(file_bytes: bytes) -> str:
    """
    Extract text from Excel files (.xlsx, .xls).
    Converts all sheets to text format with clear section markers.
    """
    try:
        # Read Excel file from bytes
        excel_file = io.BytesIO(file_bytes)
        excel_data = pd.read_excel(excel_file, sheet_name=None, engine='openpyxl')
        
        text_parts = []
        
        for sheet_name, df in excel_data.items():
            # Add sheet name as a section header
            text_parts.append(f"Sheet: {sheet_name}")
            text_parts.append("=" * 50)
            
            # Convert DataFrame to string representation
            # Replace NaN with empty string for cleaner output
            df_filled = df.fillna('')
            
            # Convert to string with headers
            sheet_text = df_filled.to_string(index=False)
            text_parts.append(sheet_text)
            text_parts.append("")  # Empty line between sheets
        
        result = "\n\n".join(text_parts)
        logger.info("Extracted %d sheet(s) from Excel file", len(excel_data))
        return result
        
    except Exception as e:
        logger.error("Failed to extract Excel file: %s", str(e))
        raise ValueError(f"Could not parse Excel file: {str(e)}")
