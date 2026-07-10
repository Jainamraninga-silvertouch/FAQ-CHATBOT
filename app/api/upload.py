"""
Upload API: POST /upload, GET /documents, DELETE /documents/{id}

Thin routing layer only — all real logic lives in services/.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.models.schemas import DeleteResponse, DocumentSummary, UploadResponse
from app.services.memory_store import MemoryStore, get_memory_store
from app.services.parser import UnsupportedFileTypeError, extract_text
from app.services.json_converter import build_document

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])

_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    store: MemoryStore = Depends(get_memory_store),
) -> UploadResponse:
    file_bytes = await file.read()

    if len(file_bytes) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File exceeds 20 MB limit.")

    try:
        raw_text = extract_text(file_bytes, file.filename)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface parse failures as 422s
        logger.exception("Failed to parse uploaded file %s", file.filename)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Could not extract text from '{file.filename}': {exc}",
        ) from exc

    if store.find_by_filename(file.filename) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A document with the filename '{file.filename}' has already been uploaded.",
        )

    document = build_document(filename=file.filename, raw_text=raw_text)
    store.add(document)

    logger.info("Uploaded document %s (%s), %d sections",
                document.document_id, document.filename, len(document.content))

    return UploadResponse(
        document_id=document.document_id,
        filename=document.filename,
        num_sections=len(document.content),
    )


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(store: MemoryStore = Depends(get_memory_store)) -> list[DocumentSummary]:
    return store.list_summaries()


@router.delete("/documents/{document_id}", response_model=DeleteResponse)
async def delete_document(
    document_id: str,
    store: MemoryStore = Depends(get_memory_store),
) -> DeleteResponse:
    deleted = store.delete(document_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Document '{document_id}' not found.")
    return DeleteResponse(document_id=document_id, deleted=True, message="Document deleted.")
