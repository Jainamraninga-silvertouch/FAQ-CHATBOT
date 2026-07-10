"""
FastAPI app entrypoint.

Wires together the API routers and serves the static frontend. Run with:
    uvicorn main:app --reload --port 8000
    
Documents are automatically loaded from the /upload directory at startup.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from app.api import chat, upload
from app.services.document_loader import load_all_documents
from app.services.memory_store import get_memory_store

# Load environment variables from .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logging.info(f"Loaded environment variables from {env_path}")
else:
    logging.warning(".env file not found. Make sure GROQ_API_KEY is set in your environment.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="Document FAQ Chatbot",
    description="A simple in-memory RAG-ready FAQ chatbot that answers only from uploaded documents.",
    version="1.0.0",
)

# Permissive CORS for local development; tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Load all documents from /upload directory at startup."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Starting Document FAQ Chatbot")
    logger.info("=" * 60)

    # Load documents from upload directory into the persistent store
    documents = load_all_documents()

    if documents:
        store = get_memory_store()
        added = 0
        skipped = 0
        for doc in documents:
            if store.find_by_filename(doc.filename) is not None:
                skipped += 1
                logger.info("Skipping already-loaded document: %s", doc.filename)
                continue
            store.add(doc)
            added += 1
        logger.info("✓ Loaded %d new document(s) into persistent storage", added)
        if skipped:
            logger.info("✓ Skipped %d already-loaded document(s)", skipped)
        logger.info("Documents:")
        for doc in store.all_documents():
            logger.info(f"  - {doc.filename} ({len(doc.content)} sections)")
    else:
        logger.warning("⚠ No documents found in /upload directory")
        logger.info("  Place PDF, DOCX, TXT, or XLSX files in the /upload folder")
    
    logger.info("=" * 60)
    logger.info("Server ready at http://localhost:8000")
    logger.info("=" * 60)


app.include_router(upload.router)
app.include_router(chat.router)


@app.get("/api/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok"}


# Serve the simple frontend (index.html, script.js, style.css) at "/".
app.mount("/", StaticFiles(directory="static", html=True), name="static")
