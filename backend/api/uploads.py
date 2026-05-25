"""File uploads: CV PDFs, interview audio recordings, and voice-prompt clips."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.config import DATA_DIR, load_settings
from backend.storage.sessions import get_session
from backend.tools.cv_parser import extract_cv_text
from backend.tools.transcribe import get_cached_provider, language_to_iso

router = APIRouter(prefix="/api/uploads")

AUDIO_DIR = DATA_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_AUDIO_EXT = {".m4a", ".mp3", ".wav", ".webm", ".ogg", ".flac", ".mp4"}


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


@router.post("/interview-audio")
async def upload_interview_audio(
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    filename = file.filename or "recording"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported audio format: {suffix or '(none)'}",
        )

    max_bytes = load_settings().transcription.max_file_mb * 1024 * 1024
    target = AUDIO_DIR / f"{session_id}_{uuid.uuid4().hex}{suffix}"
    written = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"file exceeds {max_bytes // (1024 * 1024)} MB limit",
                )
            out.write(chunk)

    return {
        "audio_path": str(target),
        "filename": filename,
        "size_bytes": written,
    }


voice_router = APIRouter(prefix="/api/transcribe")


@voice_router.post("/voice-prompt")
async def transcribe_voice_prompt(
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    """Transcribe a short voice clip into text for prompt entry.

    Audio is ephemeral — written to a temp file, transcribed, then deleted.
    Language hint is derived from the session's chosen language.
    """
    settings = load_settings().transcription
    max_bytes = settings.voice_max_mb * 1024 * 1024

    suffix = Path(file.filename or "voice.webm").suffix.lower() or ".webm"
    target = AUDIO_DIR / f"voice_{uuid.uuid4().hex}{suffix}"
    written = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"clip exceeds {settings.voice_max_mb} MB limit",
                    )
                out.write(chunk)

        if written == 0:
            raise HTTPException(status_code=400, detail="empty audio payload")

        session = await get_session(session_id)
        language_hint = language_to_iso((session or {}).get("language"))

        provider = get_cached_provider(settings)
        result = await provider.transcribe(target, language=language_hint)
    finally:
        target.unlink(missing_ok=True)

    return {
        "text": result.full_text,
        "language": result.language,
        "duration_sec": result.duration_sec,
    }
