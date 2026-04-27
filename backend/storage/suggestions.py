"""Per-profile suggestion inbox: proposed edits to candidate_profile awaiting user approval."""

from __future__ import annotations

import json
import time
from typing import Any

from backend.storage.db import connect


async def insert_suggestion(
    *,
    profile_id: str,
    diff: dict[str, Any],
    confidence: int,
    source_application_ids: list[int],
    kind: str = "candidate_profile_edit",
) -> int:
    async with connect() as db:
        cur = await db.execute(
            """
            INSERT INTO profile_suggestions (
                profile_id, kind, diff, confidence, status,
                source_application_ids, created_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                profile_id,
                kind,
                json.dumps(diff),
                max(1, int(confidence)),
                json.dumps(source_application_ids),
                time.time(),
            ),
        )
        await db.commit()
        return cur.lastrowid or 0


def _row_to_suggestion(r: Any) -> dict[str, Any]:
    return {
        "id": r[0],
        "profile_id": r[1],
        "kind": r[2],
        "diff": json.loads(r[3]) if r[3] else {},
        "confidence": r[4],
        "status": r[5],
        "source_application_ids": json.loads(r[6]) if r[6] else [],
        "created_at": r[7],
        "resolved_at": r[8],
    }


async def list_pending(profile_id: str) -> list[dict[str, Any]]:
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT id, profile_id, kind, diff, confidence, status,
                   source_application_ids, created_at, resolved_at
            FROM profile_suggestions
            WHERE profile_id = ? AND status = 'pending'
            ORDER BY created_at DESC
            """,
            (profile_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_suggestion(r) for r in rows]


async def get_suggestion(suggestion_id: int) -> dict[str, Any] | None:
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT id, profile_id, kind, diff, confidence, status,
                   source_application_ids, created_at, resolved_at
            FROM profile_suggestions WHERE id = ?
            """,
            (suggestion_id,),
        )
        row = await cur.fetchone()
    return _row_to_suggestion(row) if row else None


async def _set_status(suggestion_id: int, status: str) -> bool:
    async with connect() as db:
        cur = await db.execute(
            "UPDATE profile_suggestions SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
            (status, time.time(), suggestion_id),
        )
        await db.commit()
    return (cur.rowcount or 0) > 0


async def reject_suggestion(suggestion_id: int) -> bool:
    return await _set_status(suggestion_id, "rejected")


async def dismiss_suggestion(suggestion_id: int) -> bool:
    return await _set_status(suggestion_id, "dismissed")


async def approve_suggestion(suggestion_id: int) -> dict[str, Any] | None:
    """Mark suggestion approved and apply its diff to profiles.candidate_profile.

    Returns the updated suggestion row, or None if not found / not pending.
    """
    suggestion = await get_suggestion(suggestion_id)
    if not suggestion or suggestion["status"] != "pending":
        return None
    diff = suggestion.get("diff") or {}
    new_text = diff.get("after")
    if not isinstance(new_text, str):
        return None
    now = time.time()
    async with connect() as db:
        cur = await db.execute(
            """
            UPDATE profiles SET candidate_profile = ?, updated_at = ?
            WHERE profile_id = ?
            """,
            (new_text, now, suggestion["profile_id"]),
        )
        if (cur.rowcount or 0) == 0:
            await db.commit()
            return None
        await db.execute(
            "UPDATE profile_suggestions SET status = 'approved', resolved_at = ? WHERE id = ?",
            (now, suggestion_id),
        )
        await db.commit()
    return await get_suggestion(suggestion_id)


async def count_pending(profile_id: str) -> int:
    async with connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM profile_suggestions WHERE profile_id = ? AND status = 'pending'",
            (profile_id,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0
