"""
Persistent document store.

This keeps uploaded FAQ documents on disk under the project's storage folder,
so the chatbot retains its data across server restarts.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

from app.models.schemas import Document, DocumentSummary


class MemoryStore:
    """Thread-safe file-backed store keyed by document_id."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        # Allow overriding storage location from env var for cloud mounts (e.g. Render disk)
        env_path = os.environ.get("STORAGE_PATH")
        default_path = Path(__file__).resolve().parent.parent.parent / "storage"
        self._storage_dir = Path(storage_dir or env_path or default_path)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._documents: Dict[str, Document] = {}
        self._lock = threading.Lock()
        self._load_from_disk()

    def _storage_path(self, document_id: str) -> Path:
        return self._storage_dir / f"{document_id}.json"

    def _load_from_disk(self) -> None:
        if not self._storage_dir.exists():
            return

        for file_path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                document = Document(**data)
                self._documents[document.document_id] = document
            except Exception:
                continue

    def _save_to_disk(self, document: Document) -> None:
        payload = document.model_dump()
        self._storage_path(document.document_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _delete_from_disk(self, document_id: str) -> None:
        path = self._storage_path(document_id)
        if path.exists():
            path.unlink()

    def add(self, document: Document) -> None:
        with self._lock:
            self._documents[document.document_id] = document
            self._save_to_disk(document)

    def get(self, document_id: str) -> Optional[Document]:
        with self._lock:
            return self._documents.get(document_id)

    def delete(self, document_id: str) -> bool:
        with self._lock:
            if document_id in self._documents:
                del self._documents[document_id]
                self._delete_from_disk(document_id)
                return True
            return False

    def list_summaries(self) -> List[DocumentSummary]:
        with self._lock:
            return [
                DocumentSummary(
                    document_id=doc.document_id,
                    filename=doc.filename,
                    num_sections=len(doc.content),
                )
                for doc in self._documents.values()
            ]

    def all_documents(self) -> List[Document]:
        with self._lock:
            return list(self._documents.values())

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._documents) == 0


memory_store = MemoryStore()


def get_memory_store() -> MemoryStore:
    """Dependency-injectable accessor for the singleton store."""
    return memory_store
