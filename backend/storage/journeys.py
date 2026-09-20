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
        "job_screenshot_path",
        "job_source_type",
        "alignment_strategy",
        "inferred_role_context",
        "positioning_strategy",
        "cover_letter",
        "interview_briefing",
        "evaluation_summary",
        "export_folder",
        # Tracker dates. There is no status field — see derive_status().
        "applied_at",
        "on_hold_at",
        "rejected_at",
        "dropped_at",
        "offer_at",
        "notes",
        "next_step",
        "next_step_at",
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
    "job_screenshot_path",
    "job_source_type",
    "alignment_strategy",
    "inferred_role_context",
    "positioning_strategy",
    "cover_letter",
    "interview_briefing",
    "evaluation_summary",
    "export_folder",
    "cover_letter_at",
    "interview_briefing_at",
    "evaluation_summary_at",
    "applied_at",
    "on_hold_at",
    "rejected_at",
    "dropped_at",
    "offer_at",
    "notes",
    "next_step",
    "next_step_at",
    "created_at",
    "updated_at",
)

# Writing one of these artifact fields also records when it was generated.
_ARTIFACT_STAMPS = {
    "cover_letter": "cover_letter_at",
    "interview_briefing": "interview_briefing_at",
    "evaluation_summary": "evaluation_summary_at",
}


# The tracker's eight states. Never stored — see derive_status().
STATUSES = (
    "draft",
    "applied",
    "silent",
    "in_progress",
    "on_hold",
    "offer",
    "rejected",
    "dropped",
)

# Mirrors AppSettings.quiet_after_days. Callers that show the user a status pass
# the configured value; this default only keeps the function usable on its own.
DEFAULT_QUIET_AFTER_DAYS = 30


def last_contact_at(
    journey: dict[str, Any],
    interviews: list[dict[str, Any]] | tuple = (),
    feedback: list[dict[str, Any]] | tuple = (),
) -> float | None:
    """The most recent moment anything happened *to* this application.

    Events are deliberately excluded: a follow-up you sent is not a reply, and
    chasing a company that is ignoring you should not make the application look
    alive again.
    """
    stamps = [
        journey.get("applied_at"),
        *(i.get("scheduled_at") for i in interviews),
        *(f.get("created_at") for f in feedback),
    ]
    return max((s for s in stamps if s), default=None)


def derive_status(
    journey: dict[str, Any],
    interviews: list[dict[str, Any]],
    *,
    now: float | None = None,
    feedback: list[dict[str, Any]] | tuple = (),
    quiet_after_days: int = DEFAULT_QUIET_AFTER_DAYS,
) -> str:
    """Status is whatever the dates say it is, evaluated top to bottom.

    Keeping it a function rather than a column means a status can never drift
    from the dates that define it, and exports, prompts and the UI all agree on
    what 'in_progress' means.

    One rung — `silent` — also reads the clock, so a row's status can change
    overnight with nothing written. That is safe precisely because it is never
    stored; pass `now` to keep tests from going stale.
    """
    if journey.get("rejected_at"):
        return "rejected"  # terminal: nothing below is consulted
    if journey.get("offer_at"):
        return "offer"
    if journey.get("dropped_at"):
        return "dropped"

    last_round = max(
        (i["scheduled_at"] for i in interviews if i.get("scheduled_at")), default=None
    )

    on_hold_at = journey.get("on_hold_at")
    if on_hold_at:
        # A round dated after the hold means the hold was lifted.
        if last_round is not None and last_round > on_hold_at:
            return "in_progress"
        return "on_hold"

    if last_round is not None:
        return "in_progress"

    applied_at = journey.get("applied_at")
    if applied_at:
        # Applied and nothing since. No round can be dated here — one would have
        # returned in_progress above — so only the employer saying something
        # resets the clock.
        contact = last_contact_at(journey, interviews, feedback) or applied_at
        quiet_for = (time.time() if now is None else now) - contact
        return "silent" if quiet_for > quiet_after_days * 86_400 else "applied"
    return "draft"


def _row_to_journey(r: Any) -> dict[str, Any]:
    return dict(zip(_COLUMNS, r))


async def create_journey(*, profile_id: str | None, **fields: Any) -> str:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown journey field(s): {sorted(unknown)}")

    journey_id = uuid.uuid4().hex
    now = time.time()
    stamps = {_ARTIFACT_STAMPS[f]: now for f, v in fields.items() if f in _ARTIFACT_STAMPS and v}
    cols = ["journey_id", "profile_id", *fields.keys(), *stamps.keys(), "created_at", "updated_at"]
    values = [journey_id, profile_id, *fields.values(), *stamps.values(), now, now]
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

    now = time.time()
    stamps = {_ARTIFACT_STAMPS[f]: now for f, v in fields.items() if f in _ARTIFACT_STAMPS and v}
    assignments = {**fields, **stamps}
    set_clause = ", ".join(f"{col} = ?" for col in assignments)
    values = [*assignments.values(), now, journey_id]

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
    profile_id: str | None = None, query: str = "", limit: int | None = 10
) -> list[dict[str, Any]]:
    """Journeys, newest first. ``limit=None`` returns all of them — the tracker
    shows every application, not a page."""
    sql = f"SELECT {', '.join(_COLUMNS)} FROM job_journeys WHERE 1 = 1"
    params: list[Any] = []
    if profile_id is not None:
        sql += " AND profile_id = ?"
        params.append(profile_id)
    if query:
        sql += " AND (company_name LIKE ? COLLATE NOCASE OR job_title LIKE ? COLLATE NOCASE)"
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY updated_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    async with connect() as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [_row_to_journey(r) for r in rows]


async def delete_journey(journey_id: str) -> bool:
    async with connect() as db:
        # SQLite runs with foreign_keys OFF by default, so the ON DELETE CASCADE
        # declared on job_feedback and job_events never fires — drop them explicitly.
        await db.execute("DELETE FROM job_feedback WHERE journey_id = ?", (journey_id,))
        await db.execute("DELETE FROM job_events WHERE journey_id = ?", (journey_id,))
        cur = await db.execute("DELETE FROM job_journeys WHERE journey_id = ?", (journey_id,))
        await db.commit()
        return cur.rowcount > 0
