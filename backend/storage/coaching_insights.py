"""Per-profile coaching insights from past interview evaluations."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

from backend.storage.db import connect


async def save_coaching_insight(
    profile_id: str | None,
    session_id: str,
    evaluation_dict: dict[str, Any],
    job_title: str = "",
    company_name: str = "",
) -> None:
    if not profile_id:
        return
    comm = evaluation_dict.get("communication") or {}
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO coaching_insights
                (profile_id, session_id, job_title, company_name,
                 overall_score, decision, summary,
                 weaknesses, improvements, filler_words, pace, clarity, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                session_id,
                job_title or "",
                company_name or "",
                evaluation_dict.get("overall_score"),
                evaluation_dict.get("decision"),
                evaluation_dict.get("summary", ""),
                json.dumps(evaluation_dict.get("weaknesses") or []),
                json.dumps(evaluation_dict.get("improvements") or []),
                json.dumps(comm.get("filler_words") or []),
                comm.get("pace"),
                comm.get("clarity"),
                time.time(),
            ),
        )
        await db.commit()


async def get_coaching_history(
    profile_id: str | None, limit: int = 3
) -> list[dict[str, Any]]:
    if not profile_id:
        return []
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT profile_id, session_id, job_title, company_name,
                   overall_score, decision, summary,
                   weaknesses, improvements, filler_words, pace, clarity, created_at
            FROM coaching_insights
            WHERE profile_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (profile_id, limit),
        )
        rows = await cur.fetchall()
    return [
        {
            "profile_id": row["profile_id"],
            "session_id": row["session_id"],
            "job_title": row["job_title"],
            "company_name": row["company_name"],
            "overall_score": row["overall_score"],
            "decision": row["decision"],
            "summary": row["summary"],
            "weaknesses": json.loads(row["weaknesses"]),
            "improvements": json.loads(row["improvements"]),
            "filler_words": json.loads(row["filler_words"]),
            "pace": row["pace"],
            "clarity": row["clarity"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
