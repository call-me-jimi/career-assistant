"""Per-round persistence: job interviews.

A job journey can involve several interview rounds. Each row here is one round,
so a briefing produced by the Interview Prep assistant can be matched to the
recording the Interview Evaluator later analyses.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.storage.db import connect

# Round taxonomy: slug → (label, one-line hint).
INTERVIEW_TYPES: dict[str, tuple[str, str]] = {
    "recruiter": ("Recruiter", "external or internal recruiter — logistics and fit"),
    "screening": ("Screening", "first HR/talent round, CV walk-through"),
    "hiring_manager": ("Hiring manager", "the manager who owns the role"),
    "technical": ("Technical", "coding, architecture or domain deep-dive"),
    "case_study": ("Case study / presentation", "case, take-home or live presentation"),
    "panel": ("Panel", "several interviewers at once"),
    "team_peer": ("Team / peer", "future colleagues — culture and collaboration"),
    "leadership": ("Leadership", "director, VP or C-level — strategy and vision"),
    "final": ("Final round", "closing round, offer/negotiation adjacent"),
    "mixed": ("Mixed", "spans several of the above"),
    "other": ("Other", "anything else"),
}

# Extra spellings users type at the picker, mapped onto a slug.
_TYPE_ALIASES: dict[str, str] = {
    "hm": "hiring_manager",
    "manager": "hiring_manager",
    "hiring": "hiring_manager",
    "tech": "technical",
    "technical_interview": "technical",
    "case": "case_study",
    "case_study_presentation": "case_study",
    "presentation": "case_study",
    "peer": "team_peer",
    "team": "team_peer",
    "team/peer": "team_peer",
    "culture": "team_peer",
    "hr": "screening",
    "phone_screen": "screening",
    "executive": "leadership",
    "c_level": "leadership",
    "final_round": "final",
}


def type_label(slug: str) -> str:
    entry = INTERVIEW_TYPES.get(slug)
    return entry[0] if entry else (slug or "Unspecified round")


def describe_type(slug: str, label: str = "") -> str:
    """One-line round description for prompts. Empty when the round is unclassified."""
    if not slug:
        return ""
    name, hint = INTERVIEW_TYPES.get(slug, (slug, ""))
    text = f"{name} — {hint}" if hint else name
    return f'{text} (the candidate calls it "{label}")' if label else text


def resolve_type(text: str) -> str | None:
    """Map free text ('technical', 'Hiring manager', 'team/peer') onto a slug."""
    raw = (text or "").strip().lower()
    if not raw:
        return None
    key = raw.replace(" ", "_").replace("-", "_")
    if key in INTERVIEW_TYPES:
        return key
    if key in _TYPE_ALIASES:
        return _TYPE_ALIASES[key]
    if raw in _TYPE_ALIASES:
        return _TYPE_ALIASES[raw]
    for slug, (label, _hint) in INTERVIEW_TYPES.items():
        if raw == label.lower():
            return slug
    return None


_ALLOWED_FIELDS = frozenset(
    {
        "interview_type",
        "label",
        "context",
        "briefing",
        "evaluation_summary",
    }
)

_COLUMNS = (
    "interview_id",
    "journey_id",
    "profile_id",
    "interview_type",
    "label",
    "context",
    "briefing",
    "evaluation_summary",
    "briefing_at",
    "evaluation_at",
    "created_at",
    "updated_at",
)

# Writing one of these artifact fields also records when it was produced.
_ARTIFACT_STAMPS = {
    "briefing": "briefing_at",
    "evaluation_summary": "evaluation_at",
}


def _row_to_interview(r: Any) -> dict[str, Any]:
    return dict(zip(_COLUMNS, r))


async def create_interview(
    *, journey_id: str, profile_id: str | None, **fields: Any
) -> str:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown interview field(s): {sorted(unknown)}")

    interview_id = uuid.uuid4().hex
    now = time.time()
    stamps = {_ARTIFACT_STAMPS[f]: now for f, v in fields.items() if f in _ARTIFACT_STAMPS and v}
    cols = [
        "interview_id",
        "journey_id",
        "profile_id",
        *fields.keys(),
        *stamps.keys(),
        "created_at",
        "updated_at",
    ]
    values = [interview_id, journey_id, profile_id, *fields.values(), *stamps.values(), now, now]
    placeholders = ", ".join("?" for _ in values)

    async with connect() as db:
        await db.execute(
            f"INSERT INTO job_interviews ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        await db.commit()
    return interview_id


async def update_interview(interview_id: str, **fields: Any) -> None:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown interview field(s): {sorted(unknown)}")

    now = time.time()
    stamps = {_ARTIFACT_STAMPS[f]: now for f, v in fields.items() if f in _ARTIFACT_STAMPS and v}
    assignments = {**fields, **stamps}
    set_clause = ", ".join(f"{col} = ?" for col in assignments)
    values = [*assignments.values(), now, interview_id]

    async with connect() as db:
        await db.execute(
            f"UPDATE job_interviews SET {set_clause}, updated_at = ? WHERE interview_id = ?",
            values,
        )
        await db.commit()


async def get_interview(interview_id: str) -> dict[str, Any] | None:
    async with connect() as db:
        cur = await db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM job_interviews WHERE interview_id = ?",
            (interview_id,),
        )
        row = await cur.fetchone()
    return _row_to_interview(row) if row else None


async def list_interviews(journey_id: str) -> list[dict[str, Any]]:
    """Rounds of one journey, oldest first — the order they were interviewed in."""
    async with connect() as db:
        cur = await db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM job_interviews "
            "WHERE journey_id = ? ORDER BY created_at ASC",
            (journey_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_interview(r) for r in rows]
