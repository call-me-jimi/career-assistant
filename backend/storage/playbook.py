"""Per-profile learned playbook: structured guidance injected into cover-letter generation."""

from __future__ import annotations

import json
import time
from typing import Any

from backend.storage.db import connect

# The list-valued categories. Each item may carry `shared: true`, meaning the
# candidate promoted it to every CV — see list_shared_items().
LIST_CATEGORIES = (
    "never_say",
    "prefer_phrasing",
    "recurring_hm_weaknesses",
    "employer_feedback_themes",
)

# Which key holds an item's text, per category. Used to dedupe own items against
# shared ones from another profile.
_LABEL_KEY = {
    "never_say": "phrase",
    "prefer_phrasing": "phrase",
    "recurring_hm_weaknesses": "weakness",
    "employer_feedback_themes": "theme",
}


def _shared_flag(item: Any) -> bool:
    return bool(item.get("shared")) if isinstance(item, dict) else False


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
            items.append({"phrase": phrase, "reason": reason, "shared": _shared_flag(item)})
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
            items.append({"weakness": weakness, "shared": _shared_flag(item)})
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
            items.append({"theme": theme, "evidence": evidence, "shared": _shared_flag(item)})
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


async def set_item_shared(
    profile_id: str, category: str, index: int, shared: bool
) -> bool:
    """Promote one learned item to every CV, or stop it spreading.

    Nothing crosses profiles on its own: a lesson is learned for the profile that
    earned it, and only this makes it readable elsewhere. Clearing the flag stops
    future injection — it cannot reach back into a playbook whose synthesis has
    already absorbed the item, which is why sharing is described as one-way.
    """
    if category not in LIST_CATEGORIES:
        return False
    playbook = await get_playbook(profile_id)
    items = playbook.get(category) or []
    if not (0 <= index < len(items)) or not isinstance(items[index], dict):
        return False
    items[index]["shared"] = bool(shared)
    playbook[category] = items
    await upsert_playbook(profile_id, playbook)
    return True


async def list_shared_items(exclude_profile_id: str) -> dict[str, list[dict[str, Any]]]:
    """Items other profiles have promoted to every CV, by category.

    Each carries `profile_id` so the UI can say where a lesson came from; that key
    is added on read and never stored.
    """
    async with connect() as db:
        cur = await db.execute(
            f"SELECT profile_id, {', '.join(LIST_CATEGORIES)} "
            "FROM profile_playbook WHERE profile_id != ?",
            (exclude_profile_id,),
        )
        rows = await cur.fetchall()

    out: dict[str, list[dict[str, Any]]] = {c: [] for c in LIST_CATEGORIES}
    for row in rows:
        for offset, category in enumerate(LIST_CATEGORIES, start=1):
            for item in json.loads(row[offset] or "[]"):
                if isinstance(item, dict) and item.get("shared"):
                    out[category].append({**item, "profile_id": row[0]})
    return out


def _label(category: str, item: Any) -> str:
    key = _LABEL_KEY.get(category, "")
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get(key, ""))
    return ""


def merge_shared(
    playbook: dict[str, Any], shared: dict[str, list[dict[str, Any]]] | None
) -> dict[str, Any]:
    """The playbook a prompt should actually see: this profile's items, plus what
    other profiles have promoted. Own items win — a profile that already learned
    something keeps its own wording for it."""
    if not shared:
        return playbook
    merged = dict(playbook)
    for category in LIST_CATEGORIES:
        own = list(playbook.get(category) or [])
        seen = {_label(category, i) for i in own}
        for item in shared.get(category) or []:
            label = _label(category, item)
            if label and label not in seen:
                own.append(item)
                seen.add(label)
        merged[category] = own
    return merged


def render_playbook_for_prompt(
    playbook: dict[str, Any], shared: dict[str, list[dict[str, Any]]] | None = None
) -> str:
    """Render the playbook as a plain-text block to inject into the generation prompt.

    Returns empty string when the playbook has no content — callers should treat an
    empty string as "no guidance, behave exactly like the prior version".
    """
    playbook = merge_shared(playbook, shared)
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
