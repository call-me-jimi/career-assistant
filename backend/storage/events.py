"""Per-job event log for the application tracker.

A dated line of what happened — a follow-up sent, a recruiter who called on
WhatsApp, an invitation missed. Deliberately never consulted when deriving a
job's status: only the journey's dates and its rounds' dates do that.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.storage.db import connect

KINDS = ("note", "follow_up", "contact")

_ALLOWED_FIELDS = frozenset({"kind", "occurred_at", "text"})

_COLUMNS = (
    "event_id",
    "journey_id",
    "kind",
    "occurred_at",
    "text",
    "created_at",
)


def _row_to_event(r: Any) -> dict[str, Any]:
    return dict(zip(_COLUMNS, r))


async def add_event(
    *, journey_id: str, occurred_at: float, text: str = "", kind: str = "note"
) -> str:
    if kind not in KINDS:
        raise ValueError(f"Unknown event kind: {kind}")

    event_id = uuid.uuid4().hex
    async with connect() as db:
        await db.execute(
            "INSERT INTO job_events (event_id, journey_id, kind, occurred_at, text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, journey_id, kind, occurred_at, text, time.time()),
        )
        await db.commit()
    return event_id


async def update_event(event_id: str, **fields: Any) -> None:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown event field(s): {sorted(unknown)}")
    if "kind" in fields and fields["kind"] not in KINDS:
        raise ValueError(f"Unknown event kind: {fields['kind']}")
    if not fields:
        return

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    async with connect() as db:
        await db.execute(
            f"UPDATE job_events SET {set_clause} WHERE event_id = ?",
            [*fields.values(), event_id],
        )
        await db.commit()


async def list_events(journey_id: str) -> list[dict[str, Any]]:
    """Events of one journey, most recent first."""
    async with connect() as db:
        cur = await db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM job_events "
            "WHERE journey_id = ? ORDER BY occurred_at DESC, created_at DESC",
            (journey_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_event(r) for r in rows]


async def delete_event(event_id: str) -> bool:
    async with connect() as db:
        cur = await db.execute("DELETE FROM job_events WHERE event_id = ?", (event_id,))
        await db.commit()
        return cur.rowcount > 0
