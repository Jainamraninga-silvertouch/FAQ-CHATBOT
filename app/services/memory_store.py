"""
In-memory document store.

This is Phase 1's "database". It is deliberately isolated behind a small
class-based interface (get / add / delete / list / all_sections) so that
swapping it for a real database or vector store later means writing a new
class with the same methods — no changes needed in api/ or elsewhere.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from app.models.schemas import Document, DocumentSummary


class MemoryStore:
    """Thread-safe in-memory store keyed by document_id."""

    def __init__(self) -> None:
        self._documents: Dict[str, Document] = {}
        self._lock = threading.Lock()

    def add(self, document: Document) -> None:
        with self._lock:
            self._documents[document.document_id] = document

    def get(self, document_id: str) -> Optional[Document]:
        return self._documents.get(document_id)

    def delete(self, document_id: str) -> bool:
        with self._lock:
            if document_id in self._documents:
                del self._documents[document_id]
                return True
            return False

    def list_summaries(self) -> List[DocumentSummary]:
        return [
            DocumentSummary(
                document_id=doc.document_id,
                filename=doc.filename,
                num_sections=len(doc.content),
            )
            for doc in self._documents.values()
        ]

    def all_documents(self) -> List[Document]:
        return list(self._documents.values())

    def is_empty(self) -> bool:
        return len(self._documents) == 0


# Singleton instance used across the app. FastAPI's dependency injection
# (see api/upload.py / api/chat.py) returns this same instance per request,
# which is what keeps documents "in memory" for the life of the server process.
memory_store = MemoryStore()


def get_memory_store() -> MemoryStore:
    """Dependency-injectable accessor for the singleton store."""
    return memory_store
