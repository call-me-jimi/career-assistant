"""Per-job persistence: job journeys shared across the Cover Letter, Interview Prep,
and Interview Evaluator assistants so a job's artifacts survive across sessions."""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.storage.db import connect

_ALLOWED_FIELDS = frozenset(
    {
        "job_url",
        "job_title",
        "company_name",
        "location",
        "job_description",
        "company_description",
        "job_ad_language",
        "job_source_type",
        "alignment_strategy",
        "inferred_role_context",
        "positioning_strategy",
        "cover_letter",
        "interview_briefing",
        "evaluation_summary",
    }
)

_COLUMNS = (
    "journey_id",
    "profile_id",
    "job_url",
    "job_title",
    "company_name",
    "location",
    "job_description",
    "company_description",
    "job_ad_language",
    "job_source_type",
    "alignment_strategy",
    "inferred_role_context",
    "positioning_strategy",
    "cover_letter",
    "interview_briefing",
    "evaluation_summary",
    "created_at",
    "updated_at",
)


def _row_to_journey(r: Any) -> dict[str, Any]:
    return dict(zip(_COLUMNS, r))


async def create_journey(*, profile_id: str | None, **fields: Any) -> str:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown journey field(s): {sorted(unknown)}")

    journey_id = uuid.uuid4().hex
    now = time.time()
    cols = ["journey_id", "profile_id", *fields.keys(), "created_at", "updated_at"]
    values = [journey_id, profile_id, *fields.values(), now, now]
    placeholders = ", ".join("?" for _ in values)

    async with connect() as db:
        await db.execute(
            f"INSERT INTO job_journeys ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        await db.commit()
    return journey_id


async def update_journey(journey_id: str, **fields: Any) -> None:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown journey field(s): {sorted(unknown)}")

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = [*fields.values(), time.time(), journey_id]

    async with connect() as db:
        await db.execute(
            f"UPDATE job_journeys SET {set_clause}, updated_at = ? WHERE journey_id = ?",
            values,
        )
        await db.commit()


async def get_journey(journey_id: str) -> dict[str, Any] | None:
    async with connect() as db:
        cur = await db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM job_journeys WHERE journey_id = ?",
            (journey_id,),
        )
        row = await cur.fetchone()
    return _row_to_journey(row) if row else None


async def find_journey(
    *, profile_id: str | None, job_url: str, company_name: str, job_title: str
) -> dict[str, Any] | None:
    async with connect() as db:
        if job_url:
            cur = await db.execute(
                f"""
                SELECT {', '.join(_COLUMNS)} FROM job_journeys
                WHERE COALESCE(profile_id, '') = COALESCE(?, '') AND job_url = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (profile_id, job_url),
            )
        else:
            cur = await db.execute(
                f"""
                SELECT {', '.join(_COLUMNS)} FROM job_journeys
                WHERE COALESCE(profile_id, '') = COALESCE(?, '')
                  AND lower(company_name) = lower(?)
                  AND lower(job_title) = lower(?)
                ORDER BY updated_at DESC LIMIT 1
                """,
                (profile_id, company_name, job_title),
            )
        row = await cur.fetchone()
    return _row_to_journey(row) if row else None


async def list_journeys(
    profile_id: str | None = None, query: str = "", limit: int = 10
) -> list[dict[str, Any]]:
    sql = f"SELECT {', '.join(_COLUMNS)} FROM job_journeys WHERE 1 = 1"
    params: list[Any] = []
    if profile_id is not None:
        sql += " AND profile_id = ?"
        params.append(profile_id)
    if query:
        sql += " AND (company_name LIKE ? COLLATE NOCASE OR job_title LIKE ? COLLATE NOCASE)"
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    async with connect() as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [_row_to_journey(r) for r in rows]


async def delete_journey(journey_id: str) -> bool:
    async with connect() as db:
        cur = await db.execute("DELETE FROM job_journeys WHERE journey_id = ?", (journey_id,))
        await db.commit()
        return cur.rowcount > 0
