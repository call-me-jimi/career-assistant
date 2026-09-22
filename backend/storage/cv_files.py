"""The original CV file behind a profile.

The upload arrives before any profile exists — cv_intake asks for the label, and
may not save at all — so it is staged under an upload id first and moved into
place when a profile claims it. Staged files nobody claimed are swept on the
next upload.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from backend.config import DATA_DIR
from backend.storage.db import connect

STAGING_DIR = DATA_DIR / "cv_uploads"
CV_DIR = DATA_DIR / "cvs"
STALE_AFTER_S = 24 * 3600


def _safe_name(filename: str | None) -> str:
    return Path(filename or "").name or "cv.pdf"


def stage_upload(data: bytes, filename: str | None) -> str:
    """Keep an uploaded CV until a profile claims it; returns its upload id."""
    _sweep_stale()
    upload_id = uuid.uuid4().hex
    folder = STAGING_DIR / upload_id
    folder.mkdir(parents=True)
    (folder / _safe_name(filename)).write_bytes(data)
    return upload_id


def _sweep_stale() -> None:
    if not STAGING_DIR.exists():
        return
    cutoff = time.time() - STALE_AFTER_S
    for folder in STAGING_DIR.iterdir():
        if folder.is_dir() and folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)


def cv_path(profile_id: str, cv_filename: str) -> Path:
    return CV_DIR / f"{profile_id}{Path(cv_filename).suffix.lower()}"


async def _store(profile_id: str, data_path: Path, filename: str) -> None:
    async with connect() as db:
        cur = await db.execute(
            "SELECT cv_filename FROM profiles WHERE profile_id = ?", (profile_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise LookupError(profile_id)
        CV_DIR.mkdir(parents=True, exist_ok=True)
        if row[0]:
            cv_path(profile_id, row[0]).unlink(missing_ok=True)
        shutil.move(str(data_path), cv_path(profile_id, filename))
        await db.execute(
            "UPDATE profiles SET cv_filename = ? WHERE profile_id = ?",
            (filename, profile_id),
        )
        await db.commit()


async def claim_upload(profile_id: str, upload_id: str) -> bool:
    """Move a staged upload onto a profile. False if it is gone (swept, or never existed)."""
    folder = STAGING_DIR / Path(upload_id).name
    files = [f for f in folder.iterdir() if f.is_file()] if folder.is_dir() else []
    if not files:
        return False
    await _store(profile_id, files[0], files[0].name)
    shutil.rmtree(folder, ignore_errors=True)
    return True


async def attach_cv(profile_id: str, data: bytes, filename: str | None) -> str:
    """Attach (or replace) a profile's original CV file. Raises LookupError for an unknown profile."""
    name = _safe_name(filename)
    CV_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CV_DIR / f".{uuid.uuid4().hex}.part"
    tmp.write_bytes(data)
    try:
        await _store(profile_id, tmp, name)
    finally:
        tmp.unlink(missing_ok=True)
    return name


def remove_cv(profile_id: str, cv_filename: str | None) -> None:
    if cv_filename:
        cv_path(profile_id, cv_filename).unlink(missing_ok=True)
