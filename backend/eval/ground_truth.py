"""Ground truth that already exists in the database, linked back to traces.

Sessions rarely carry a journey id, so the link is by content: a round's stored
briefing is the response text of the trace that wrote it, and a round's stored
evaluation summary is the "summary" field of the evaluator trace that wrote it.
"""

from __future__ import annotations

import json
from typing import Any

from backend.eval.scorers import parse_json
from backend.eval.store import _rows


async def _rounds() -> list[dict[str, Any]]:
    """Every (briefing, evaluation) pair: per interview round, plus the older
    job-level fields from before rounds existed. Carries the dates that give an outcome."""
    rounds = await _rows(
        "SELECT i.interview_id, i.journey_id, i.briefing, i.evaluation_summary, "
        "COALESCE(i.scheduled_at, i.created_at) AS at, j.rejected_at, j.offer_at "
        "FROM job_interviews i JOIN job_journeys j USING (journey_id)"
    )
    rounds += await _rows(
        "SELECT NULL AS interview_id, journey_id, interview_briefing AS briefing, "
        "evaluation_summary, NULL AS at, rejected_at, offer_at FROM job_journeys"
    )
    return rounds


async def _evaluator_traces() -> dict[str, dict[str, Any]]:
    """summary text → {trace_id, per_question} for every parsable evaluator trace."""
    out: dict[str, dict[str, Any]] = {}
    for t in await _rows(
        "SELECT trace_id, response_text FROM traces WHERE task='analyze_interview_performance'"
    ):
        parsed = parse_json(t["response_text"] or "")
        if parsed and parsed.get("summary"):
            out[parsed["summary"]] = {"trace_id": t["trace_id"],
                                      "per_question": parsed.get("per_question") or []}
    return out


def _summary(evaluation_summary: str) -> str | None:
    try:
        return (json.loads(evaluation_summary) or {}).get("summary")
    except (json.JSONDecodeError, AttributeError):
        return None


async def _briefing_trace(briefing: str) -> int | None:
    """The interview_briefing trace behind a stored briefing — directly, or via the
    refine trace that produced it, whose session's first briefing call is the one to replay."""
    rows = await _rows(
        "SELECT trace_id, task, session_id FROM traces WHERE response_text=? "
        "AND task IN ('interview_briefing', 'refine_interview_briefing') ORDER BY created_at",
        (briefing,),
    )
    for r in rows:
        if r["task"] == "interview_briefing":
            return r["trace_id"]
    if rows:
        first = await _rows(
            "SELECT trace_id FROM traces WHERE session_id=? AND task='interview_briefing' "
            "ORDER BY created_at LIMIT 1",
            (rows[0]["session_id"],),
        )
        return first[0]["trace_id"] if first else None
    return None


async def briefing_questions() -> dict[int, list[str]]:
    """interview_briefing trace id → the questions the evaluator found in the real interview."""
    evals = await _evaluator_traces()
    out: dict[int, list[str]] = {}
    for r in await _rounds():
        if not r["briefing"] or not r["evaluation_summary"]:
            continue
        ev = evals.get(_summary(r["evaluation_summary"]) or "")
        questions = [q.get("question", "") for q in (ev or {}).get("per_question", [])]
        questions = [q for q in questions if q]
        trace_id = await _briefing_trace(r["briefing"]) if questions else None
        if trace_id:
            out[trace_id] = questions
    return out


async def evaluator_outcomes() -> dict[int, str]:
    """analyze_interview_performance trace id → "advanced" | "rejected".

    Advanced when a later round of the same job exists or the job ended in an offer;
    rejected when it was the last round of a rejected job. Rounds with neither are
    left out rather than guessed.
    """
    evals = await _evaluator_traces()
    rounds = await _rounds()
    later: dict[str, list[float]] = {}
    for r in rounds:
        if r["interview_id"] and r["at"]:
            later.setdefault(r["journey_id"], []).append(r["at"])
    out: dict[int, str] = {}
    for r in rounds:
        ev = evals.get(_summary(r["evaluation_summary"] or "") or "")
        if not ev:
            continue
        # A round followed by another one advanced, even if the job was rejected later.
        if r["at"] and any(t > r["at"] for t in later.get(r["journey_id"], [])):
            out[ev["trace_id"]] = "advanced"
        elif r["rejected_at"]:
            out[ev["trace_id"]] = "rejected"
        elif r["offer_at"]:
            out[ev["trace_id"]] = "advanced"
    return out
