"""Aggregate statistics across all sessions and traces."""

from __future__ import annotations

from backend.storage.db import connect


async def get_global_stats() -> dict:
    """Return session counts and trace aggregates grouped by assistant_type."""
    async with connect() as db:
        cur = await db.execute(
            "SELECT assistant_type, COUNT(*) FROM sessions GROUP BY assistant_type"
        )
        session_rows = await cur.fetchall()

        cur = await db.execute(
            """
            SELECT s.assistant_type, t.model,
                   COUNT(*) as calls,
                   COALESCE(SUM(t.input_tokens), 0) as input_tokens,
                   COALESCE(SUM(t.output_tokens), 0) as output_tokens
            FROM traces t
            JOIN sessions s ON s.session_id = t.session_id
            GROUP BY s.assistant_type, t.model
            """
        )
        trace_rows = await cur.fetchall()

    sessions_by_type: dict[str, int] = {}
    for assistant_type, count in session_rows:
        sessions_by_type[assistant_type] = count

    # raw trace aggregates keyed by (assistant_type, model)
    raw: list[tuple[str, str | None, int, int, int]] = [
        (row[0], row[1], row[2], row[3], row[4]) for row in trace_rows
    ]

    return {"sessions_by_type": sessions_by_type, "trace_rows": raw}
