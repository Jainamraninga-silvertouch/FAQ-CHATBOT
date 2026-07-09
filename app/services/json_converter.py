"""
JSON converter service: turns raw extracted text into a structured
Document (a list of {section, text} entries), matching the schema
described in the project spec.

Heuristic used (no ML required):
  - Short lines (e.g. "Leave Policy", "1. Introduction", "WORK HOURS")
    are treated as section headings.
  - Everything until the next heading is that section's body text.
  - If no headings are detected at all, the whole document becomes a
    single "General" section (still valid JSON, still searchable).

This keeps Phase 1 dependency-free while leaving an obvious seam: later,
this function's output feeds directly into a Chunker for the RAG version
(see services/search.py docstring for the migration note).
"""
from __future__ import annotations

import re
import uuid
from typing import List

from app.models.schemas import Document, DocumentSection

_HEADING_MAX_WORDS = 8
_HEADING_PATTERN = re.compile(
    r"^\s*(?:\d+[.)]\s*)?[A-Z][A-Za-z0-9 ,&/'-]{2,60}$"
)


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line.split()) > _HEADING_MAX_WORDS:
        return False
    if line.endswith((".", "?", "!", ",")):
        return False
    return bool(_HEADING_PATTERN.match(line))


def text_to_sections(raw_text: str) -> List[DocumentSection]:
    """Split raw text into a list of DocumentSection objects."""
    lines = [ln.strip() for ln in raw_text.splitlines()]
    lines = [ln for ln in lines if ln != ""]

    sections: List[DocumentSection] = []
    current_heading = "General"
    current_body: list[str] = []

    def flush():
        body = " ".join(current_body).strip()
        if body:
            sections.append(DocumentSection(section=current_heading, text=body))

    for line in lines:
        if _looks_like_heading(line):
            flush()
            current_heading = line
            current_body = []
        else:
            current_body.append(line)

    flush()

    if not sections:
        # Whole document was blank / unparseable — still return something
        # valid rather than raising, so the API never fails silently.
        sections = [DocumentSection(section="General", text=raw_text.strip() or "(empty document)")]

    return sections


def build_document(filename: str, raw_text: str) -> Document:
    """Create a fully structured Document ready for storage."""
    return Document(
        document_id=str(uuid.uuid4()),
        filename=filename,
        content=text_to_sections(raw_text),
    )


def build_document_from_sections(
    filename: str,
    sections: List[DocumentSection],
    document_id: str | None = None,
) -> Document:
    """
    Build a Document from sections that are already structured — used by
    the /upload/json endpoint, which skips text extraction and heading
    detection entirely because the caller has already done that work.
    """
    return Document(
        document_id=document_id or str(uuid.uuid4()),
        filename=filename,
        content=sections,
    )
