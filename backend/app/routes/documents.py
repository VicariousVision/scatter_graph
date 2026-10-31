import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

router = APIRouter(tags=["documents"])


@router.get("/documents")
def list_documents(request: Request) -> list[dict[str, Any]]:
    return request.app.state.ingestion.list_documents()


@router.post("/documents", status_code=202)
async def upload_document(request: Request, file: UploadFile) -> dict[str, Any]:
    """Accept a PDF and queue it for knowledge-graph extraction."""
    settings = request.app.state.settings
    ingestion = request.app.state.ingestion

    # Only the base name is kept, for display. The file is stored under a generated id.
    file_name = Path(file.filename or "document.pdf").name[:200]
    if not file_name.lower().endswith(".pdf"):
        raise HTTPException(415, "Only PDF files are supported.")

    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(415, "The file is not a valid PDF.")

    file_hash = hashlib.sha256(data).hexdigest()
    duplicate = await run_in_threadpool(ingestion.find_duplicate, file_hash)
    if duplicate:
        raise HTTPException(409, f"This file is already in the knowledge base as '{duplicate}'.")

    job = await run_in_threadpool(ingestion.submit, file_name, data, file_hash)
    return {**job.to_dict(), "chunks": 0, "entities": 0}
