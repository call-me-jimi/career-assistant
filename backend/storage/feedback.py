"""Per-job employer feedback: what a company told the candidate about an application.

Feedback belongs to a job journey and may cover several interview rounds at once — a
recruiter usually summarises the whole loop in one message — so `interview_ids` is a JSON
list and an empty list means "the whole process".

`outcome` is recorded for the job timeline only. It is never a learning signal: a rejection
is not evidence about how the candidate performed, and the candidate has no way to know
whether it was. Only `feedback_text` ever teaches anything.

`outcome` is also never supplied by a caller. It is snapshotted from `derive_status()` when
the row is written, so it can never disagree with the dates on `job_journeys` — the dates own
the outcome, and this column is a copy taken at the moment the feedback arrived.
"""

from __future__ import annotations

import json
import time
from typing import Any
import uuid

from backend.storage.db import connect
from backend.storage.interviews import describe_type, list_interviews
from backend.storage.journeys import derive_status, get_journey

STAGES = ("application", "screening", "interview", "final", "offer", "unknown")
# "" is what a job that has not ended yet snapshots to — feedback can arrive
# mid-process, long before there is any outcome to record. "ghosted" is kept so
# rows written before v0.13.0 still load; nothing writes it any more.
OUTCOMES = ("rejected", "ghosted", "withdrawn", "offer", "")
SOURCES = ("recruiter", "hiring_manager", "ats", "other", "")

_STATUS_TO_OUTCOME = {
    "rejected": "rejected",
    "offer": "offer",
    "dropped": "withdrawn",
}

# Which stage a round implies, when feedback doesn't say. Anything not listed is
# a middle round.
_TYPE_TO_STAGE = {
    "recruiter": "screening",
    "screening": "screening",
    "final": "final",
    "leadership": "final",
}

_COLUMNS = (
    "feedback_id",
    "journey_id",
    "profile_id",
    "interview_ids",
    "stage",
    "outcome",
    "source",
    "feedback_text",
    "created_at",
)

_STAGE_LABELS = {
    "application": "after applying",
    "screening": "after the screening call",
    "interview": "after an interview round",
    "final": "after the final round",
    "offer": "at offer stage",
    "unknown": "",
}

_SOURCE_LABELS = {
    "recruiter": "recruiter",
    "hiring_manager": "hiring manager",
    "ats": "automated reply",
}


def _row_to_feedback(r: Any) -> dict[str, Any]:
    entry = dict(zip(_COLUMNS, r))
    entry["interview_ids"] = json.loads(entry["interview_ids"] or "[]")
    return entry


def infer_stage(interviews: list[dict[str, Any]]) -> str:
    """Where in the process feedback landed, read from the rounds that happened.

    ``unknown`` when there are none — a caller who knows better should say so
    rather than have a guess written into the record.
    """
    dated = [i for i in interviews if i.get("scheduled_at")]
    if not dated:
        return "unknown"
    latest = max(dated, key=lambda i: i["scheduled_at"])
    return _TYPE_TO_STAGE.get(latest.get("interview_type", ""), "interview")


async def _snapshot_outcome(journey_id: str) -> str:
    """What the job's dates say has happened, right now. Empty while it is still open."""
    journey = await get_journey(journey_id)
    if not journey:
        return ""
    interviews = await list_interviews(journey_id)
    return _STATUS_TO_OUTCOME.get(derive_status(journey, interviews), "")


async def add_feedback(
    *,
    journey_id: str,
    profile_id: str | None,
    interview_ids: list[str] | None = None,
    stage: str = "unknown",
    source: str = "",
    feedback_text: str = "",
) -> str:
    """Record what an employer said. ``outcome`` is not a parameter — see the
    module docstring; it is read from the job's dates as they stand now."""
    if stage not in STAGES:
        raise ValueError(f"Unknown feedback stage: {stage!r}")
    if source not in SOURCES:
        raise ValueError(f"Unknown feedback source: {source!r}")

    outcome = await _snapshot_outcome(journey_id)
    feedback_id = uuid.uuid4().hex
    placeholders = ", ".join("?" for _ in _COLUMNS)
    async with connect() as db:
        await db.execute(
            f"INSERT INTO job_feedback ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            (
                feedback_id,
                journey_id,
                profile_id,
                json.dumps(list(interview_ids or [])),
                stage,
                outcome,
                source,
                feedback_text.strip(),
                time.time(),
            ),
        )
        await db.commit()
    return feedback_id


async def list_feedback(journey_id: str) -> list[dict[str, Any]]:
    """Every feedback entry for one job, oldest first — the job's timeline."""
    async with connect() as db:
        cur = await db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM job_feedback "
            "WHERE journey_id = ? ORDER BY created_at",
            (journey_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_feedback(r) for r in rows]


async def list_recent_feedback(
    profile_id: str | None, limit: int = 5, company_name: str = ""
) -> list[dict[str, Any]]:
    """Recent feedback for a profile, for injection into prompts.

    Entries with no text are skipped — a rejection that said nothing carries no
    information. Entries for `company_name` are always included regardless of the
    window and sort first: re-applying to a company that already told you why they
    said no is the case worth spending prompt budget on.

    Each entry is enriched with the job's `job_title` and `company_name`.
    """
    if not profile_id:
        return []

    async with connect() as db:
        cur = await db.execute(
            f"""
            SELECT {', '.join('f.' + c for c in _COLUMNS)}, j.job_title, j.company_name
            FROM job_feedback f
            JOIN job_journeys j ON j.journey_id = f.journey_id
            WHERE f.profile_id = ? AND TRIM(f.feedback_text) != ''
            ORDER BY f.created_at DESC
            """,
            (profile_id,),
        )
        rows = await cur.fetchall()

    entries: list[dict[str, Any]] = []
    for r in rows:
        entry = _row_to_feedback(r[: len(_COLUMNS)])
        entry["job_title"] = r[len(_COLUMNS)]
        entry["company_name"] = r[len(_COLUMNS) + 1]
        entries.append(entry)

    key = company_name.casefold() if company_name else None
    same_company: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for entry in entries:
        target = same_company if key and (entry["company_name"] or "").casefold() == key else others
        target.append(entry)

    return same_company + others[: max(0, limit - len(same_company))]


async def delete_feedback(feedback_id: str) -> bool:
    async with connect() as db:
        cur = await db.execute(
            "DELETE FROM job_feedback WHERE feedback_id = ?", (feedback_id,)
        )
        await db.commit()
        return cur.rowcount > 0


def _entry_context(entry: dict[str, Any]) -> str:
    """The parenthetical after the job: who said it, at what point."""
    parts = [
        _SOURCE_LABELS.get(entry.get("source") or "", ""),
        _STAGE_LABELS.get(entry.get("stage") or "", ""),
        time.strftime("%Y-%m-%d", time.localtime(entry.get("created_at") or 0)),
    ]
    return ", ".join(p for p in parts if p)


def render_feedback_for_prompt(entries: list[dict[str, Any]]) -> str:
    """Render feedback entries as a plain-text block to inject into a prompt.

    Neutral data only — no instructions. How to weigh the feedback differs per
    consumer, so the guardrail framing lives in each template, not here.

    Returns empty string when there is nothing to render; callers must treat that
    as "no feedback, behave exactly like the prior prompt version".
    """
    lines: list[str] = []
    for entry in entries:
        text = (entry.get("feedback_text") or "").strip()
        if not text:
            continue
        company = entry.get("company_name") or "Unknown company"
        title = entry.get("job_title") or ""
        header = f"{company} — {title}" if title else company
        context = _entry_context(entry)
        lines.append(f"{header} ({context}):" if context else f"{header}:")
        lines.append(f'"{text}"')
        lines.append("")

    return "\n".join(lines).strip()


async def employer_feedback_block(
    profile_id: str | None, *, limit: int, company_name: str = ""
) -> str:
    """Fetch and render recent feedback in one call — what the prompt-side nodes want.

    Empty string when there is nothing, so a caller can pass it straight through to a
    template whose block is guarded by `{% if employer_feedback %}`.
    """
    return render_feedback_for_prompt(
        await list_recent_feedback(profile_id, limit=limit, company_name=company_name)
    )


async def list_evaluator_calibration(
    profile_id: str | None, limit: int | None = None, journey_id: str = ""
) -> list[dict[str, Any]]:
    """Pair each past evaluator verdict with what the employer said about that round.

    A pair needs both halves, so this stays empty until a job has an evaluation *and*
    feedback. Feedback pinned to rounds pairs with exactly those; feedback covering the
    whole process (`interview_ids == []`, the usual shape of a recruiter's summary) fans
    out to every evaluated round of that job, so one message calibrates the screening
    read, the hiring-manager read and the leadership read separately.

    `limit` caps how many pairs come back and defaults to uncapped — the cap belongs to
    the caller that has a prompt budget to spend. `journey_id` narrows to one job, which
    is what the job detail page shows.

    `outcome` is deliberately absent from the result. Whether the candidate was hired
    says nothing about whether the evaluator read the room correctly, and the candidate
    cannot tell a performance rejection from a frozen budget.
    """
    if not profile_id:
        return []

    async with connect() as db:
        cur = await db.execute(
            f"""
            SELECT f.journey_id, f.interview_ids, f.stage, f.source, f.feedback_text,
                   f.created_at, j.job_title, j.company_name
            FROM job_feedback f
            JOIN job_journeys j ON j.journey_id = f.journey_id
            WHERE f.profile_id = ? AND TRIM(f.feedback_text) != ''
            {"AND f.journey_id = ?" if journey_id else ""}
            ORDER BY f.created_at DESC
            """,
            (profile_id, journey_id) if journey_id else (profile_id,),
        )
        feedback_rows = await cur.fetchall()
        if not feedback_rows:
            return []

        cur = await db.execute(
            """
            SELECT journey_id, interview_id, overall_score, decision, summary,
                   weaknesses, improvements
            FROM coaching_insights
            WHERE profile_id = ? AND journey_id IS NOT NULL
            ORDER BY created_at DESC
            """,
            (profile_id,),
        )
        eval_rows = await cur.fetchall()
        if not eval_rows:
            return []

        journey_ids = sorted({r[0] for r in feedback_rows})
        cur = await db.execute(
            "SELECT interview_id, interview_type, label FROM job_interviews "
            f"WHERE journey_id IN ({', '.join('?' for _ in journey_ids)})",
            journey_ids,
        )
        round_rows = await cur.fetchall()

    rounds = {r[0]: describe_type(r[1], r[2]) for r in round_rows}

    by_interview: dict[str, dict[str, Any]] = {}
    by_journey: dict[str, list[dict[str, Any]]] = {}
    for journey_id, interview_id, score, decision, summary, weaknesses, improvements in eval_rows:
        # Rows are newest first, so the first verdict seen for a round is the current one;
        # a re-evaluation supersedes rather than duplicates.
        if interview_id and interview_id in by_interview:
            continue
        verdict = {
            "interview_id": interview_id,
            "overall_score": score,
            "decision": decision,
            "summary": summary or "",
            "weaknesses": json.loads(weaknesses) if weaknesses else [],
            "improvements": json.loads(improvements) if improvements else [],
        }
        if interview_id:
            by_interview[interview_id] = verdict
        by_journey.setdefault(journey_id, []).append(verdict)

    pairs: list[dict[str, Any]] = []
    for row in feedback_rows:
        journey_id, interview_ids, stage, source, text, created_at, job_title, company = row
        pinned = json.loads(interview_ids or "[]")
        if pinned:
            verdicts = [by_interview[i] for i in pinned if i in by_interview]
        else:
            verdicts = by_journey.get(journey_id, [])

        for verdict in verdicts:
            pairs.append(
                {
                    # For the UI only: the calibration page reads the job's dates to
                    # split verdicts by what actually happened. It is not rendered into
                    # the evaluator prompt — render_calibration_for_prompt() whitelists
                    # its fields, and an outcome must never reach the evaluator.
                    "journey_id": journey_id,
                    "company_name": company or "",
                    "job_title": job_title or "",
                    "interview_id": verdict["interview_id"],
                    "round": rounds.get(verdict["interview_id"] or "", ""),
                    "assistant_said": {
                        k: v for k, v in verdict.items() if k != "interview_id"
                    },
                    "employer_said": text,
                    "stage": stage,
                    "source": source,
                    "created_at": created_at,
                }
            )
            if limit is not None and len(pairs) >= limit:
                return pairs

    return pairs


def render_calibration_for_prompt(pairs: list[dict[str, Any]]) -> str:
    """Render calibration pairs as a plain-text block for the evaluator prompt.

    Data only — the framing that tells the evaluator how to weigh these (and what not to
    infer from them) lives in the template. The evaluation's free-text summary is carried
    on the pair for the UI but left out here: the weaknesses are the calibration-relevant
    part, and summaries are long enough to crowd the prompt.

    Returns empty string when there is nothing to render; callers must treat that as
    "no pairs, behave exactly like the prior prompt version".
    """
    blocks: list[str] = []
    for pair in pairs:
        employer_said = (pair.get("employer_said") or "").strip()
        if not employer_said:
            continue

        said = pair.get("assistant_said") or {}
        company = pair.get("company_name") or "Unknown company"
        title = pair.get("job_title") or ""
        lines = [f"{company} — {title}" if title else company]
        if pair.get("round"):
            lines.append(f"Round: {pair['round']}")

        score = said.get("overall_score")
        verdict = ", ".join(
            p
            for p in (
                f"{score}/10" if score is not None else "",
                said.get("decision") or "",
            )
            if p
        )
        if verdict:
            lines.append(f"You assessed: {verdict}")

        weaknesses = [str(w) for w in (said.get("weaknesses") or []) if w]
        if weaknesses:
            lines.append("Weaknesses you raised: " + "; ".join(weaknesses))

        context = _entry_context(pair)
        lines.append(
            f'They said ({context}): "{employer_said}"'
            if context
            else f'They said: "{employer_said}"'
        )
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks).strip()
