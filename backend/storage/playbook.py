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
        "employer_feedback_themes": [],
        "tone_notes": "",
        "updated_at": None,
    }


async def get_playbook(profile_id: str) -> dict[str, Any]:
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT never_say, prefer_phrasing, recurring_hm_weaknesses,
                   employer_feedback_themes, tone_notes, updated_at
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
        "employer_feedback_themes": json.loads(row[3]) if row[3] else [],
        "tone_notes": row[4] or "",
        "updated_at": row[5],
    }


def _normalize_phrase_items(raw: Any) -> list[dict[str, str]]:
    """Coerce a phrase list (never_say / prefer_phrasing) to a list of {phrase, reason} dicts.

    The synthesis LLM occasionally emits bare strings instead of dicts; normalize
    at write time so stored rows always have a consistent shape.
    """
    items: list[dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, str):
            phrase, reason = item, ""
        elif isinstance(item, dict):
            phrase, reason = str(item.get("phrase", "")), str(item.get("reason", ""))
        else:
            continue
        if phrase:
            items.append({"phrase": phrase, "reason": reason})
    return items


def _normalize_weakness_items(raw: Any) -> list[dict[str, str]]:
    """Coerce recurring_hm_weaknesses to a list of {weakness} dicts, tolerating bare strings."""
    items: list[dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, str):
            weakness = item
        elif isinstance(item, dict):
            weakness = str(item.get("weakness", ""))
        else:
            continue
        if weakness:
            items.append({"weakness": weakness})
    return items


def _normalize_theme_items(raw: Any) -> list[dict[str, str]]:
    """Coerce employer_feedback_themes to a list of {theme, evidence} dicts.

    `evidence` is what makes a theme trustworthy — which employers said it, how often —
    so it is kept even though it is optional.
    """
    items: list[dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, str):
            theme, evidence = item, ""
        elif isinstance(item, dict):
            theme, evidence = str(item.get("theme", "")), str(item.get("evidence", ""))
        else:
            continue
        if theme:
            items.append({"theme": theme, "evidence": evidence})
    return items


async def upsert_playbook(profile_id: str, payload: dict[str, Any]) -> None:
    never_say = _normalize_phrase_items(payload.get("never_say"))
    prefer_phrasing = _normalize_phrase_items(payload.get("prefer_phrasing"))
    recurring_hm_weaknesses = _normalize_weakness_items(payload.get("recurring_hm_weaknesses"))
    employer_feedback_themes = _normalize_theme_items(payload.get("employer_feedback_themes"))
    tone_notes = payload.get("tone_notes") or ""
    now = time.time()
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO profile_playbook (
                profile_id, never_say, prefer_phrasing, recurring_hm_weaknesses,
                employer_feedback_themes, tone_notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                never_say = excluded.never_say,
                prefer_phrasing = excluded.prefer_phrasing,
                recurring_hm_weaknesses = excluded.recurring_hm_weaknesses,
                employer_feedback_themes = excluded.employer_feedback_themes,
                tone_notes = excluded.tone_notes,
                updated_at = excluded.updated_at
            """,
            (
                profile_id,
                json.dumps(never_say),
                json.dumps(prefer_phrasing),
                json.dumps(recurring_hm_weaknesses),
                json.dumps(employer_feedback_themes),
                tone_notes,
                now,
            ),
        )
        await db.commit()


async def remove_playbook_item(profile_id: str, category: str, index: int) -> bool:
    """Remove a single item from a list-valued playbook category. Returns True if removed."""
    if category not in {
        "never_say",
        "prefer_phrasing",
        "recurring_hm_weaknesses",
        "employer_feedback_themes",
    }:
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
    themes = playbook.get("employer_feedback_themes") or []
    tone = (playbook.get("tone_notes") or "").strip()

    if not (never_say or prefer or weaknesses or themes or tone):
        return ""

    lines: list[str] = []
    if tone:
        lines.append(f"Tone notes: {tone}")
    if never_say:
        lines.append("Avoid these phrasings (they have consistently been revised out):")
        for item in never_say:
            phrase, reason = _phrase_reason(item)
            if phrase:
                lines.append(f"- \"{phrase}\"" + (f" — {reason}" if reason else ""))
    if prefer:
        lines.append("Prefer these phrasings (consistently kept by the candidate):")
        for item in prefer:
            phrase, reason = _phrase_reason(item)
            if phrase:
                lines.append(f"- \"{phrase}\"" + (f" — {reason}" if reason else ""))
    if weaknesses:
        lines.append("Recurring hiring-manager concerns for this candidate — address them proactively:")
        for item in weaknesses:
            w = item if isinstance(item, str) else (item.get("weakness", "") if isinstance(item, dict) else "")
            if w:
                lines.append(f"- {w}")
    if themes:
        lines.append(
            "Recurring themes in what real employers said about past applications — "
            "address these proactively with concrete evidence. Never reference a past "
            "rejection, apologise, or hedge:"
        )
        for item in themes:
            theme, evidence = _theme_evidence(item)
            if theme:
                lines.append(f"- {theme}" + (f" ({evidence})" if evidence else ""))
    return "\n".join(lines)


def _theme_evidence(item: Any) -> tuple[str, str]:
    """Coerce an employer_feedback_themes item to (theme, evidence), tolerating bare strings."""
    if isinstance(item, str):
        return item, ""
    if isinstance(item, dict):
        return item.get("theme", ""), item.get("evidence", "")
    return "", ""


def _phrase_reason(item: Any) -> tuple[str, str]:
    """Coerce a playbook list item to (phrase, reason).

    Items are normally dicts, but the synthesis LLM occasionally emits a bare
    string; tolerate both so rendering never crashes on legacy/malformed rows.
    """
    if isinstance(item, str):
        return item, ""
    if isinstance(item, dict):
        return item.get("phrase", ""), item.get("reason", "")
    return "", ""
