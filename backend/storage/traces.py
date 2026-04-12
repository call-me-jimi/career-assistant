"""LLM call trace persistence (one row per finished LLM call)."""

from __future__ import annotations

import time
from typing import Any

from backend.storage.db import connect


async def record_trace(
    *,
    session_id: str,
    card_id: str,
    task: str | None,
    provider: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
    system_prompt: str,
    user_prompt: str,
    response_text: str,
) -> None:
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO traces (
                session_id, card_id, task, provider, model,
                input_tokens, output_tokens, duration_ms,
                system_prompt, user_prompt, response_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                card_id,
                task,
                provider,
                model,
                input_tokens,
                output_tokens,
                duration_ms,
                system_prompt,
                user_prompt,
                response_text,
                time.time(),
            ),
        )
        await db.commit()


def _row_to_dict(r: Any) -> dict[str, Any]:
    return {
        "card_id": r[0],
        "task": r[1],
        "provider": r[2],
        "model": r[3],
        "input_tokens": r[4] or 0,
        "output_tokens": r[5] or 0,
        "duration_ms": r[6] or 0,
        "system_prompt": r[7] or "",
        "user_prompt": r[8] or "",
        "response_text": r[9] or "",
        "created_at": r[10],
    }


async def list_traces(session_id: str) -> list[dict[str, Any]]:
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT card_id, task, provider, model, input_tokens, output_tokens,
                   duration_ms, system_prompt, user_prompt, response_text, created_at
            FROM traces WHERE session_id=? ORDER BY created_at ASC
            """,
            (session_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_trace(session_id: str, card_id: str) -> dict[str, Any] | None:
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT card_id, task, provider, model, input_tokens, output_tokens,
                   duration_ms, system_prompt, user_prompt, response_text, created_at
            FROM traces WHERE session_id=? AND card_id=?
            """,
            (session_id, card_id),
        )
        row = await cur.fetchone()
    return _row_to_dict(row) if row else None
