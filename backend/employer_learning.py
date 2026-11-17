"""Learn from what real employers said, each time the candidate records a reply.

The cover-letter synthesis only ran when a letter was finished and saw the five newest
replies, which are mostly boilerplate: a profile with dozens of rejections could show
nothing. This pass reads every reply the profile has and rewrites the employer part of the
playbook — `employer_strengths`, `employer_feedback_themes` (the concerns) and
`employer_feedback_stats` — and nothing else. The api schedules it whenever feedback is
added or removed.

As everywhere, only what an employer wrote teaches anything; the fact of a rejection does
not (backend/storage/feedback.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from backend.config import load_settings
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm, extract_json
from backend.storage.feedback import list_recent_feedback, render_feedback_for_prompt
from backend.storage.playbook import get_playbook, upsert_playbook

log = logging.getLogger("assistant.employer_learning")

TASK = "learn_from_employers"
# Enough for any job search's replies; a long rejection mail is cut, not dropped.
MAX_REPLIES = 100
MAX_REPLY_CHARS = 3000


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _carry_shared(new: list[Any], old: list[Any]) -> list[Any]:
    """An item the candidate shared stays shared while its wording holds."""
    shared = {i.get("theme") for i in old if isinstance(i, dict) and i.get("shared")}
    return [
        {**i, "shared": True} if isinstance(i, dict) and i.get("theme") in shared else i
        for i in new
        if isinstance(i, dict)
    ]


async def learn_from_employers(profile_id: str) -> bool:
    """Rewrite the profile's employer lessons from all its recorded replies. False when
    learning is off or the model's answer can't be used; the stored lessons stay then."""
    settings = load_settings()
    if not settings.learning_enabled:
        return False

    entries = await list_recent_feedback(profile_id, limit=MAX_REPLIES)
    playbook = await get_playbook(profile_id)
    old_strengths = playbook.get("employer_strengths") or []
    old_concerns = playbook.get("employer_feedback_themes") or []

    if not entries:
        # The last reply was removed: nothing left to learn from.
        strengths: list[Any] = []
        concerns: list[Any] = []
        unspecific = 0
    else:
        for e in entries:
            e["feedback_text"] = (e.get("feedback_text") or "")[:MAX_REPLY_CHARS]
        keys = ("theme", "evidence", "count")
        current = {
            "strengths": [{k: i.get(k) for k in keys} for i in old_strengths if isinstance(i, dict)],
            "concerns": [{k: i.get(k) for k in keys} for i in old_concerns if isinstance(i, dict)],
        }
        result = await call_llm(
            task="learn_from_employers",
            system=load_system_prompt(TASK),
            user=render_user_prompt(
                TASK,
                current_lessons=json.dumps(current, indent=2, ensure_ascii=False),
                reply_count=len(entries),
                employer_feedback=render_feedback_for_prompt(entries),
                language=settings.language,
            ),
        )
        try:
            payload = extract_json(result.text)
        except Exception:  # noqa: BLE001 - a malformed answer keeps the stored lessons
            return False
        if not isinstance(payload, dict):
            return False
        strengths = _list(payload.get("strengths"))
        concerns = _list(payload.get("concerns"))
        raw = payload.get("unspecific")
        unspecific = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
        unspecific = max(0, min(unspecific, len(entries)))

    await upsert_playbook(
        profile_id,
        {
            "employer_strengths": _carry_shared(strengths, old_strengths),
            "employer_feedback_themes": _carry_shared(concerns, old_concerns),
            "employer_feedback_stats": {
                "replies": len(entries),
                "unspecific": unspecific,
                "updated_at": time.time(),
            },
        },
    )
    return True


# --- running it in the background --------------------------------------------
#
# One run per profile at a time, and no request lost: a request marks the profile as
# wanting a run, and the profile's running task keeps going until no mark is left. A
# burst of replies is folded into as few runs as possible; each run reads every reply,
# so the last one has seen them all. All of this lives on the one event loop, so the
# check-and-start below needs no lock.

_wanted: set[str] = set()
_running: dict[str, asyncio.Task[None]] = {}


def is_learning(profile_id: str) -> bool:
    return profile_id in _running


def schedule_employer_learning(profile_id: str) -> None:
    """Learn again from the profile's replies, soon. Returns at once."""
    _wanted.add(profile_id)
    if profile_id not in _running:
        _running[profile_id] = asyncio.create_task(_drain(profile_id))


async def _drain(profile_id: str) -> None:
    try:
        while profile_id in _wanted:
            _wanted.discard(profile_id)
            try:
                await learn_from_employers(profile_id)
            except Exception:  # noqa: BLE001 - not retried; the next reply tries again
                log.exception("employer learning failed profile=%s", profile_id)
    finally:
        _running.pop(profile_id, None)
