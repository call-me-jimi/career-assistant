"""CV PDF upload → text extraction."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from backend.tools.cv_parser import extract_cv_text

router = APIRouter(prefix="/api/uploads")


@router.post("/cv")
async def upload_cv(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "cv.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        text = extract_cv_text(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {"cv_text": text, "chars": len(text)}
