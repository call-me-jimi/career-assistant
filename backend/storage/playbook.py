"""Per-profile learned playbook: structured guidance injected into cover-letter generation."""

from __future__ import annotations

import json
import time
from typing import Any

from backend.storage.db import connect


def _empty() -> dict[str, Any]:
    return {
        "never_say": [],
        "prefer_phrasing": [],
        "recurring_hm_weaknesses": [],
        "tone_notes": "",
        "updated_at": None,
    }


async def get_playbook(profile_id: str) -> dict[str, Any]:
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT never_say, prefer_phrasing, recurring_hm_weaknesses, tone_notes, updated_at
            FROM profile_playbook WHERE profile_id = ?
            """,
            (profile_id,),
        )
        row = await cur.fetchone()
    if not row:
        return _empty()
    return {
        "never_say": json.loads(row[0]) if row[0] else [],
        "prefer_phrasing": json.loads(row[1]) if row[1] else [],
        "recurring_hm_weaknesses": json.loads(row[2]) if row[2] else [],
        "tone_notes": row[3] or "",
        "updated_at": row[4],
    }


async def upsert_playbook(profile_id: str, payload: dict[str, Any]) -> None:
    never_say = payload.get("never_say") or []
    prefer_phrasing = payload.get("prefer_phrasing") or []
    recurring_hm_weaknesses = payload.get("recurring_hm_weaknesses") or []
    tone_notes = payload.get("tone_notes") or ""
    now = time.time()
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO profile_playbook (
                profile_id, never_say, prefer_phrasing, recurring_hm_weaknesses,
                tone_notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                never_say = excluded.never_say,
                prefer_phrasing = excluded.prefer_phrasing,
                recurring_hm_weaknesses = excluded.recurring_hm_weaknesses,
                tone_notes = excluded.tone_notes,
                updated_at = excluded.updated_at
            """,
            (
                profile_id,
                json.dumps(never_say),
                json.dumps(prefer_phrasing),
                json.dumps(recurring_hm_weaknesses),
                tone_notes,
                now,
            ),
        )
        await db.commit()


async def remove_playbook_item(profile_id: str, category: str, index: int) -> bool:
    """Remove a single item from a list-valued playbook category. Returns True if removed."""
    if category not in {"never_say", "prefer_phrasing", "recurring_hm_weaknesses"}:
        return False
    playbook = await get_playbook(profile_id)
    items = playbook.get(category) or []
    if not (0 <= index < len(items)):
        return False
    items.pop(index)
    playbook[category] = items
    await upsert_playbook(profile_id, playbook)
    return True


def render_playbook_for_prompt(playbook: dict[str, Any]) -> str:
    """Render the playbook as a plain-text block to inject into the generation prompt.

    Returns empty string when the playbook has no content — callers should treat an
    empty string as "no guidance, behave exactly like the prior version".
    """
    never_say = playbook.get("never_say") or []
    prefer = playbook.get("prefer_phrasing") or []
    weaknesses = playbook.get("recurring_hm_weaknesses") or []
    tone = (playbook.get("tone_notes") or "").strip()

    if not (never_say or prefer or weaknesses or tone):
        return ""

    lines: list[str] = []
    if tone:
        lines.append(f"Tone notes: {tone}")
    if never_say:
        lines.append("Avoid these phrasings (they have consistently been revised out):")
        for item in never_say:
            phrase = item.get("phrase", "")
            reason = item.get("reason", "")
            lines.append(f"- \"{phrase}\"" + (f" — {reason}" if reason else ""))
    if prefer:
        lines.append("Prefer these phrasings (consistently kept by the candidate):")
        for item in prefer:
            phrase = item.get("phrase", "")
            reason = item.get("reason", "")
            lines.append(f"- \"{phrase}\"" + (f" — {reason}" if reason else ""))
    if weaknesses:
        lines.append("Recurring hiring-manager concerns for this candidate — address them proactively:")
        for item in weaknesses:
            w = item.get("weakness", "")
            if w:
                lines.append(f"- {w}")
    return "\n".join(lines)
