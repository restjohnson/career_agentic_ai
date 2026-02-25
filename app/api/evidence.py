# app/api/evidence.py
from __future__ import annotations

import hashlib
import os
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.state import EvidenceSourceType
from app.tools.docling_parser import infer_suffix
from app.tools.session_token import get_session_id
from app.tools.supabase_repo import SupabaseRepo

router = APIRouter(prefix="/evidence", tags=["evidence"])
repo = SupabaseRepo()

_ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/html",
    "text/markdown",
    "text/plain",
}

_MAX_BYTES = 20 * 1024 * 1024  # 20 MB


class EvidenceUploadResponse(BaseModel):
    document_id: str
    content_hash: str
    storage_ref: str
    source_type: str


@router.post("", response_model=EvidenceUploadResponse)
async def upload_evidence(
    source_type: str = Form(..., description="One of: resume, transcript, portfolio, job_posting, other"),
    consent_level: str = Form(default="derived_only", description="One of: derived_only, excerpt_ok, raw_ok"),
    file: UploadFile = File(...),
    session_id: str = Depends(get_session_id),
):
    """
    Upload a student evidence file (PDF, DOCX, etc.).

    Steps:
      1. Validate file type and size.
      2. Compute SHA-256 hash for deduplication.
      3. Upload to Supabase Storage bucket `evidence-documents`.
      4. Insert an evidence_document record and return its id.

    The returned document_id can be passed to POST /runs as evidence_document_ids[].
    """
    _validate_source_type(source_type)
    _validate_consent_level(consent_level)

    file_bytes = await file.read()

    if len(file_bytes) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit.")

    content_type = file.content_type or ""
    if content_type and content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Allowed: PDF, DOCX, DOC, PPTX, HTML, MD, TXT.",
        )

    content_hash = hashlib.sha256(file_bytes).hexdigest()
    suffix = infer_suffix(file.filename, content_type)
    storage_ref = f"{session_id}/{content_hash}{suffix}"

    # Upload to Supabase Storage (upsert — same hash means same content)
    try:
        repo.upload_evidence_file(
            storage_ref=storage_ref,
            file_bytes=file_bytes,
            content_type=content_type or "application/octet-stream",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {type(e).__name__}: {e}")

    # Create DB record
    try:
        document_id = repo.insert_evidence_document(
            session_id=session_id,
            source_type=source_type,
            content_hash=content_hash,
            strorage_ref=storage_ref,
            consent_level=consent_level,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB record creation failed: {type(e).__name__}: {e}")

    return EvidenceUploadResponse(
        document_id=document_id,
        content_hash=content_hash,
        storage_ref=storage_ref,
        source_type=source_type,
    )


def _validate_source_type(value: str) -> None:
    allowed = {"resume", "transcript", "portfolio", "job_posting", "other"}
    if value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"source_type must be one of: {', '.join(sorted(allowed))}",
        )


def _validate_consent_level(value: str) -> None:
    allowed = {"derived_only", "excerpt_ok", "raw_ok"}
    if value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"consent_level must be one of: {', '.join(sorted(allowed))}",
        )
