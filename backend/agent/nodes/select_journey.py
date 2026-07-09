"""Select-journey node: continue a previously started job across sessions.

Shown to the Cover Letter, Interview Prep, and Interview Evaluator assistants
(not Career Advisor) right after cv_intake. Lists recent job journeys as a
numbered pick list; the user can continue one, start fresh (URL/pasted text),
or filter the list by typing a company name.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState
from backend.storage.journeys import get_journey, list_journeys

_SEED_FIELDS = (
    "job_url",
    "job_title",
    "company_name",
    "location",
    "job_description",
    "company_description",
    "job_ad_language",
    "job_source_type",
    "alignment_strategy",
    "inferred_role_context",
    "positioning_strategy",
    "cover_letter",
    "interview_briefing",
)


def _format_updated_at(ts: float | int | None) -> str:
    if not ts:
        return "unknown"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _artifact_badges(journey: dict) -> str:
    labels = []
    if journey.get("cover_letter"):
        labels.append("cover letter ✓")
    if journey.get("interview_briefing"):
        labels.append("briefing ✓")
    if journey.get("evaluation_summary"):
        labels.append("evaluated ✓")
    return ", ".join(labels) if labels else "no artifacts yet"


def _continue_phase(assistant_type: str, journey: dict) -> str:
    """Route to the earliest step whose data is missing; downstream static edges do the rest."""
    if assistant_type == "interview_prep":
        return "research_company" if not journey["company_description"] else "interview_context"
    if assistant_type == "interview_evaluator":
        return "evaluator_context"  # evaluator graph has no research node
    # cover_letter
    if not journey["company_description"]:
        return "research_company"
    if not journey["job_source_type"]:
        return "classify_flow"
    if not (journey["positioning_strategy"] or journey["alignment_strategy"]):
        return "strategy"
    return "cl_loop"


async def select_journey_node(state: ApplicationState) -> dict:
    sid = state.session_id
    journeys = await list_journeys(state.profile_id, query=state.journey_query, limit=10)

    if not journeys and not state.journey_query:
        return {"phase": "collect_job"}  # silent skip — current behavior

    prefix = ""
    if state.journey_query and not journeys:
        journeys = await list_journeys(state.profile_id, limit=10)
        if not journeys:
            return {"phase": "collect_job", "journey_query": ""}
        prefix = f"No matches for '{state.journey_query}' — here is the full list:\n\n"

    lines = [
        f"{i}. **{j['company_name']} — {j['job_title']}**  ({_artifact_badges(j)} · {_format_updated_at(j.get('updated_at'))})"
        for i, j in enumerate(journeys, start=1)
    ]

    emit_message(
        sid,
        prefix
        + "\n".join(lines)
        + "\n\n_Type a number to continue that journey, "
        "paste a job URL / job ad to start fresh, or type a company name to search._",
        key=f"select_journey:list:{state.journey_query}",
    )

    reply = interrupt(
        {
            "kind": "select_journey",
            "journeys": [
                {
                    "journey_id": j["journey_id"],
                    "company_name": j["company_name"],
                    "job_title": j["job_title"],
                }
                for j in journeys
            ],
        }
    )
    return await _handle_reply(state, journeys, reply)


async def _handle_reply(state: ApplicationState, journeys: list[dict], reply) -> dict:
    sid = state.session_id
    raw = (reply or "").strip()

    if raw.isdigit() and 1 <= int(raw) <= len(journeys):
        journey = await get_journey(journeys[int(raw) - 1]["journey_id"])
        if journey is None:
            return {"phase": "collect_job", "journey_query": ""}

        update: dict = {
            field: journey[field] for field in _SEED_FIELDS if journey.get(field)
        }
        update["journey_id"] = journey["journey_id"]
        update["journey_query"] = ""
        update["phase"] = _continue_phase(state.assistant_type, journey)

        emit_message(
            sid,
            f"Continuing **{journey['company_name']} — {journey['job_title']}**. "
            f"I already have {_artifact_badges(journey)}.",
        )
        return update

    if raw.lower() in {"fresh", "new", "skip", "none"}:
        emit_message(sid, "Okay — paste the URL of the posting, or the job description text.")
        return {"phase": "collect_job", "journey_query": ""}

    no_whitespace = not any(c.isspace() for c in raw)
    if raw.startswith(("http://", "https://")) or (no_whitespace and "." in raw):
        return {"job_url": raw, "phase": "collect_job", "journey_query": ""}

    if len(raw) <= 60 and "\n" not in raw:
        return {"journey_query": raw, "phase": "select_journey"}

    return {"job_raw_text": raw, "phase": "collect_job", "journey_query": ""}
