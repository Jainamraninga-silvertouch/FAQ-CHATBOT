"""
Pydantic models (schemas) used across the API layer.

Keeping all request/response contracts in one place makes it easy to see
what the API promises to callers, independent of how services implement it.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Document models
# ---------------------------------------------------------------------------

class DocumentSection(BaseModel):
    """A single searchable chunk of a document (a 'section')."""
    section: str = Field(..., description="Heading / label for this section")
    text: str = Field(..., description="Body text of this section")


class Document(BaseModel):
    """A fully parsed document stored in memory."""
    document_id: str
    filename: str
    content: List[DocumentSection]


class DocumentSummary(BaseModel):
    """Lightweight view returned by GET /documents (no full text)."""
    document_id: str
    filename: str
    num_sections: int


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    num_sections: int
    message: str = "Document uploaded and indexed successfully."


class DeleteResponse(BaseModel):
    document_id: str
    deleted: bool
    message: str


# ---------------------------------------------------------------------------
# Chat models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User's question")
    top_k: int = Field(3, ge=1, le=10, description="Number of sections to retrieve")
    document_filenames: list[str] = Field(
        default_factory=list,
        description="Optional list of filenames to restrict the search to."
    )

    # When true, bypass the normal retrieval path and ask the LLM directly.
    # This mode will not return source snippets (the model answers directly).
    use_direct_llm: bool = Field(False, description="Ask the LLM directly without retrieval")


class SourceSnippet(BaseModel):
    """A retrieved section shown back to the user for transparency."""
    document_id: str
    filename: str
    section: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceSnippet] = []
    found_context: bool
    suggested_questions: List[str] = []
