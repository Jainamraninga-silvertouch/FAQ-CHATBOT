"""
Document Loader Service

Automatically loads all documents from the /upload directory at startup.
Monitors the directory and loads any PDF, DOCX, TXT, or XLSX files found.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from app.services.parser import extract_text, UnsupportedFileTypeError
from app.services.json_converter import build_document
from app.services.product_utils import is_searchable_document
from app.models.schemas import Document

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "upload"


def ensure_upload_directory() -> Path:
    """Ensure the upload directory exists."""
    UPLOAD_DIR.mkdir(exist_ok=True)
    return UPLOAD_DIR


def get_supported_files() -> List[Path]:
    """
    Get all supported document files from the upload directory.
    Supports: .pdf, .docx, .txt, .xlsx, .xls
    """
    ensure_upload_directory()
    
    supported_extensions = {'.pdf', '.docx', '.txt', '.xlsx', '.xls'}
    files = []
    
    for file_path in UPLOAD_DIR.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
            if not is_searchable_document(file_path.name):
                logger.info(f"Skipping non-FAQ file: {file_path.name}")
                continue
            files.append(file_path)
    
    return sorted(files)


def load_document_from_file(file_path: Path) -> Document | None:
    """
    Load a single document from a file path.
    
    Returns:
        Document object if successful, None if failed
    """
    try:
        logger.info(f"Loading document: {file_path.name}")
        
        # Read file bytes
        file_bytes = file_path.read_bytes()
        
        if len(file_bytes) == 0:
            logger.warning(f"Skipping empty file: {file_path.name}")
            return None
        
        # Extract text
        raw_text = extract_text(file_bytes, file_path.name)
        
        # Build document with filename as identifier
        document = build_document(filename=file_path.name, raw_text=raw_text)
        
        logger.info(f"Successfully loaded: {file_path.name} ({len(document.content)} sections)")
        return document
        
    except UnsupportedFileTypeError as e:
        logger.warning(f"Unsupported file type: {file_path.name} - {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load {file_path.name}: {e}", exc_info=True)
        return None


def load_all_documents() -> List[Document]:
    """
    Load all supported documents from the upload directory.
    
    Returns:
        List of successfully loaded Document objects
    """
    ensure_upload_directory()
    files = get_supported_files()
    
    if not files:
        logger.info("No documents found in upload directory")
        return []
    
    logger.info(f"Found {len(files)} document(s) in upload directory")
    
    documents = []
    for file_path in files:
        document = load_document_from_file(file_path)
        if document:
            documents.append(document)
    
    logger.info(f"Successfully loaded {len(documents)} document(s)")
    return documents
