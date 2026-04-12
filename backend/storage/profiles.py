"""Candidate profile CRUD."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from backend.storage.db import connect


async def list_profiles() -> list[dict[str, Any]]:
    async with connect() as db:
        db.row_factory = None
        cur = await db.execute(
            "SELECT profile_id, name, created_at, updated_at FROM profiles ORDER BY updated_at DESC"
        )
        rows = await cur.fetchall()
    return [
        {"profile_id": r[0], "name": r[1], "created_at": r[2], "updated_at": r[3]}
        for r in rows
    ]


async def get_profile(profile_id: str) -> dict[str, Any] | None:
    async with connect() as db:
        cur = await db.execute(
            "SELECT profile_id, name, cv_text, candidate_profile, created_at, updated_at "
            "FROM profiles WHERE profile_id = ?",
            (profile_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    raw = row[3]
    if raw:
        try:
            candidate_profile: Any = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            candidate_profile = raw
    else:
        candidate_profile = ""
    return {
        "profile_id": row[0],
        "name": row[1],
        "cv_text": row[2],
        "candidate_profile": candidate_profile,
        "created_at": row[4],
        "updated_at": row[5],
    }


async def save_profile(
    *,
    name: str,
    cv_text: str,
    candidate_profile: Any,
    profile_id: str | None = None,
) -> str:
    pid = profile_id or str(uuid.uuid4())
    now = time.time()
    data = (
        candidate_profile
        if isinstance(candidate_profile, str)
        else json.dumps(candidate_profile)
    )
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO profiles (profile_id, name, cv_text, candidate_profile, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                name=excluded.name,
                cv_text=excluded.cv_text,
                candidate_profile=excluded.candidate_profile,
                updated_at=excluded.updated_at
            """,
            (pid, name, cv_text, data, now, now),
        )
        await db.commit()
    return pid
