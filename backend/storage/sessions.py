"""Session metadata storage."""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.storage.db import connect


async def create_session() -> str:
    session_id = str(uuid.uuid4())
    now = time.time()
    async with connect() as db:
        await db.execute(
            "INSERT INTO sessions (session_id, applicant_name, phase, created_at, last_activity) "
            "VALUES (?, NULL, 'greeting', ?, ?)",
            (session_id, now, now),
        )
        await db.commit()
    return session_id


async def touch_session(
    session_id: str,
    *,
    applicant_name: str | None = None,
    phase: str | None = None,
) -> None:
    now = time.time()
    async with connect() as db:
        if applicant_name is not None and phase is not None:
            await db.execute(
                "UPDATE sessions SET applicant_name=?, phase=?, last_activity=? WHERE session_id=?",
                (applicant_name, phase, now, session_id),
            )
        elif applicant_name is not None:
            await db.execute(
                "UPDATE sessions SET applicant_name=?, last_activity=? WHERE session_id=?",
                (applicant_name, now, session_id),
            )
        elif phase is not None:
            await db.execute(
                "UPDATE sessions SET phase=?, last_activity=? WHERE session_id=?",
                (phase, now, session_id),
            )
        else:
            await db.execute(
                "UPDATE sessions SET last_activity=? WHERE session_id=?",
                (now, session_id),
            )
        await db.commit()


async def get_session(session_id: str) -> dict[str, Any] | None:
    async with connect() as db:
        cur = await db.execute(
            "SELECT session_id, applicant_name, phase, created_at, last_activity "
            "FROM sessions WHERE session_id=?",
            (session_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "session_id": row[0],
        "applicant_name": row[1],
        "phase": row[2],
        "created_at": row[3],
        "last_activity": row[4],
    }
