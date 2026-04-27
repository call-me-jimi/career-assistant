"""Per-application persistence: completed cover-letter applications + HM iterations."""

from __future__ import annotations

import json
import time
from typing import Any

from backend.storage.db import connect


async def insert_application_record(
    *,
    profile_id: str,
    session_id: str,
    job_title: str,
    company_name: str,
    job_source_type: str,
    initial_cl: str,
    final_cl: str,
    revision_count: int,
    hm_feedback_final: dict[str, Any] | None,
    revision_feedback: list[dict[str, Any]],
) -> int:
    async with connect() as db:
        cur = await db.execute(
            """
            INSERT INTO application_records (
                profile_id, session_id, job_title, company_name, job_source_type,
                initial_cl, final_cl, revision_count,
                hm_feedback_final, revision_feedback, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                session_id,
                job_title,
                company_name,
                job_source_type,
                initial_cl,
                final_cl,
                revision_count,
                json.dumps(hm_feedback_final) if hm_feedback_final else None,
                json.dumps(revision_feedback),
                time.time(),
            ),
        )
        await db.commit()
        return cur.lastrowid or 0


async def insert_hm_iteration(
    *,
    application_record_id: int,
    iteration: int,
    score: float | None,
    strengths: list[str],
    weaknesses: list[str],
    suggestions: list[str],
) -> None:
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO application_hm_iterations (
                application_record_id, iteration, score,
                strengths, weaknesses, suggestions
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                application_record_id,
                iteration,
                score,
                json.dumps(strengths),
                json.dumps(weaknesses),
                json.dumps(suggestions),
            ),
        )
        await db.commit()


def _row_to_record(r: Any) -> dict[str, Any]:
    return {
        "id": r[0],
        "profile_id": r[1],
        "session_id": r[2],
        "job_title": r[3],
        "company_name": r[4],
        "job_source_type": r[5],
        "initial_cl": r[6],
        "final_cl": r[7],
        "revision_count": r[8],
        "hm_feedback_final": json.loads(r[9]) if r[9] else None,
        "revision_feedback": json.loads(r[10]) if r[10] else [],
        "created_at": r[11],
    }


async def list_recent_applications(profile_id: str, limit: int = 5) -> list[dict[str, Any]]:
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT id, profile_id, session_id, job_title, company_name, job_source_type,
                   initial_cl, final_cl, revision_count,
                   hm_feedback_final, revision_feedback, created_at
            FROM application_records
            WHERE profile_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (profile_id, limit),
        )
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]
