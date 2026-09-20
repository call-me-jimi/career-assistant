"""REST routes: session lifecycle, profile listing, trace detail."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.agent.interrupts import emit_message
from backend.agent.runner import registry
from backend.config import KNOWN_TASKS, LLMConfig, ModelPricing, load_settings, save_settings
from backend.storage.feedback import (
    add_feedback,
    delete_feedback,
    infer_stage,
    list_evaluator_calibration,
    list_feedback,
)
from backend.storage.events import add_event, delete_event, list_events, update_event
from backend.storage.interviews import (
    INTERVIEW_TYPES,
    create_interview,
    list_interviews,
    resolve_type,
    type_label,
    update_interview,
)
from backend.storage.journeys import (
    create_journey,
    delete_journey,
    derive_status,
    get_journey,
    last_contact_at,
    list_journeys,
    update_journey,
)
from backend.storage.playbook import get_playbook, remove_playbook_item, upsert_playbook
from backend.storage.profiles import delete_profile, get_profile, list_profiles
from backend.storage.sessions import ASSISTANT_TYPES, create_session, get_session
from backend.storage.stats import get_global_stats
from backend.storage.suggestions import (
    approve_suggestion,
    count_pending,
    list_pending,
    reject_suggestion,
)
from backend.storage.traces import get_trace, list_traces

router = APIRouter(prefix="/api")


def _cost_for(model: str | None, input_tokens: int, output_tokens: int, pricing: dict[str, ModelPricing]) -> float:
    if not model or model not in pricing:
        return 0.0
    p = pricing[model]
    return (input_tokens / 1_000_000.0) * p.input_per_mtok + (output_tokens / 1_000_000.0) * p.output_per_mtok


class StartSessionPayload(BaseModel):
    assistant_type: str = "cover_letter"
    language: str = "English"
    # What the session is about, when it is launched from an application row.
    # The graph skips the pickers for whichever of these it is given.
    profile_id: str | None = None
    journey_id: str | None = None
    interview_id: str | None = None


@router.post("/sessions")
async def start_session(payload: StartSessionPayload | None = None) -> dict:
    assistant_type = (payload.assistant_type if payload else "cover_letter") or "cover_letter"
    language = (payload.language if payload else "English") or "English"
    if assistant_type not in ASSISTANT_TYPES:
        raise HTTPException(400, f"unknown assistant_type: {assistant_type}")

    journey_id = payload.journey_id if payload else None
    interview_id = payload.interview_id if payload else None
    profile_id = payload.profile_id if payload else None

    if journey_id:
        journey = await get_journey(journey_id)
        if not journey:
            raise HTTPException(404, "journey not found")
        # The job's owner wins over anything the client sent.
        profile_id = journey["profile_id"] or profile_id
        if interview_id:
            rounds = {i["interview_id"] for i in await list_interviews(journey_id)}
            if interview_id not in rounds:
                raise HTTPException(400, "interview round is not on this job")
    elif interview_id:
        raise HTTPException(400, "interview_id needs a journey_id")

    session_id = await create_session(
        assistant_type,
        language,
        profile_id=profile_id,
        journey_id=journey_id,
        interview_id=interview_id,
    )
    registry.get_or_start(session_id)
    return {"session_id": session_id, "assistant_type": assistant_type, "language": language}


@router.get("/sessions/{session_id}")
async def session_info(session_id: str) -> dict:
    info = await get_session(session_id)
    if not info:
        raise HTTPException(404, "session not found")
    return info


@router.get("/profiles")
async def profiles() -> dict:
    rows = await list_profiles()
    for r in rows:
        r["pending_suggestion_count"] = await count_pending(r["profile_id"])
    return {"profiles": rows}


@router.get("/profiles/{profile_id}")
async def profile_detail(profile_id: str) -> dict:
    p = await get_profile(profile_id)
    if not p:
        raise HTTPException(404, "profile not found")
    return p


@router.delete("/profiles/{profile_id}")
async def remove_profile(profile_id: str) -> dict:
    deleted = await delete_profile(profile_id)
    if not deleted:
        raise HTTPException(404, "profile not found")
    return {"ok": True}


@router.get("/interview-types")
async def interview_types() -> dict:
    """The round taxonomy, so the tracker's type picker never keeps its own copy."""
    return {
        "types": [
            {"slug": slug, "label": label, "hint": hint}
            for slug, (label, hint) in INTERVIEW_TYPES.items()
        ]
    }


async def _with_tracker_fields(j: dict, *, quiet_after_days: int | None = None) -> dict:
    """A journey as the tracker needs it: its rounds, its events, and the status
    those dates imply. ``status`` is read-only — PATCH rejects it.

    Pass ``quiet_after_days`` when rendering a list, so the whole page shares one
    settings read; single-journey callers can let it default.
    """
    if quiet_after_days is None:
        quiet_after_days = load_settings().quiet_after_days

    # type_label comes from the backend taxonomy so the UI never has to keep its
    # own copy of the round slugs.
    journey_id = j["journey_id"]
    interviews = [
        {**i, "type_label": type_label(i["interview_type"])}
        for i in await list_interviews(journey_id)
    ]
    feedback = await list_feedback(journey_id)
    contact = last_contact_at(j, interviews, feedback)
    return {
        **j,
        "status": derive_status(
            j, interviews, feedback=feedback, quiet_after_days=quiet_after_days
        ),
        "last_contact_at": contact,
        # Days since anyone last said anything — what the table sorts and groups by.
        "waiting_days": None if contact is None else int((time.time() - contact) // 86_400),
        "interviews": interviews,
        "events": await list_events(journey_id),
        # Already fetched for the status above, and it makes what an employer said
        # searchable from the list.
        "feedback": feedback,
    }


@router.get("/journeys")
async def journeys() -> dict:
    # limit=None: the tracker is the main overview, not a page of recent jobs.
    quiet_after_days = load_settings().quiet_after_days
    rows = await list_journeys(profile_id=None, limit=None)
    return {
        "journeys": [
            await _with_tracker_fields(j, quiet_after_days=quiet_after_days) for j in rows
        ]
    }


# Declared before /journeys/{journey_id} — FastAPI matches in order, and
# "summary" would otherwise be read as a journey id.
@router.get("/journeys/summary")
async def journeys_summary() -> dict:
    """The six numbers on the landing page. Pooled across profiles: the search is
    one search, and which CV an application used is a detail of the application."""
    quiet_after_days = load_settings().quiet_after_days
    rows = await list_journeys(profile_id=None, limit=None)

    buckets = {
        "in_progress": "in_progress",
        "silent": "quiet",
        "on_hold": "on_hold",
        "rejected": "rejected",
        "dropped": "withdrawn",
    }
    counts = {"total": len(rows), **{name: 0 for name in buckets.values()}}
    for j in rows:
        journey_id = j["journey_id"]
        status = derive_status(
            j,
            await list_interviews(journey_id),
            feedback=await list_feedback(journey_id),
            quiet_after_days=quiet_after_days,
        )
        if status in buckets:
            counts[buckets[status]] += 1
    return counts


@router.get("/journeys/{journey_id}")
async def journey_detail(journey_id: str) -> dict:
    j = await get_journey(journey_id)
    if not j:
        raise HTTPException(404, "journey not found")
    return {
        **await _with_tracker_fields(j),
        "calibration": await list_evaluator_calibration(
            j["profile_id"], journey_id=journey_id
        ),
    }


# Text columns are NOT NULL, so a null from the client means "empty", not "NULL".
_JOURNEY_TEXT_FIELDS = frozenset(
    {"job_title", "company_name", "location", "job_url", "notes", "next_step"}
)


class JourneyCreatePayload(BaseModel):
    profile_id: str | None = None
    job_title: str = ""
    company_name: str = ""
    location: str = ""
    job_url: str = ""
    notes: str = ""
    applied_at: float | None = None


class JourneyPatchPayload(BaseModel):
    job_title: str | None = None
    company_name: str | None = None
    location: str | None = None
    job_url: str | None = None
    notes: str | None = None
    next_step: str | None = None
    applied_at: float | None = None
    on_hold_at: float | None = None
    rejected_at: float | None = None
    dropped_at: float | None = None
    offer_at: float | None = None
    next_step_at: float | None = None


@router.post("/journeys")
async def add_journey(payload: JourneyCreatePayload) -> dict:
    """Track a job applied to outside the assistant."""
    fields = payload.model_dump(exclude={"profile_id"})
    journey_id = await create_journey(profile_id=payload.profile_id, **fields)
    return await _with_tracker_fields(await get_journey(journey_id))


@router.patch("/journeys/{journey_id}")
async def patch_journey(journey_id: str, payload: JourneyPatchPayload) -> dict:
    if not await get_journey(journey_id):
        raise HTTPException(404, "journey not found")

    # exclude_unset is what makes clearing a date possible: an omitted field is
    # left alone, an explicit null wipes it (and so moves the status).
    fields = payload.model_dump(exclude_unset=True)
    fields = {
        k: ("" if v is None and k in _JOURNEY_TEXT_FIELDS else v) for k, v in fields.items()
    }
    if fields:
        await update_journey(journey_id, **fields)
    return await _with_tracker_fields(await get_journey(journey_id))


class InterviewCreatePayload(BaseModel):
    interview_type: str = "other"
    label: str = ""
    scheduled_at: float | None = None


class InterviewPatchPayload(BaseModel):
    interview_type: str | None = None
    label: str | None = None
    scheduled_at: float | None = None


def _resolved_type(raw: str) -> str:
    slug = resolve_type(raw)
    if not slug:
        raise HTTPException(400, f"unknown interview type: {raw}")
    return slug


@router.post("/journeys/{journey_id}/interviews")
async def add_journey_interview(journey_id: str, payload: InterviewCreatePayload) -> dict:
    """Record a round the assistant did not prepare — without this, a job you
    interviewed for elsewhere could never reach 'in_progress'."""
    journey = await get_journey(journey_id)
    if not journey:
        raise HTTPException(404, "journey not found")

    fields: dict = {
        "interview_type": _resolved_type(payload.interview_type),
        "label": payload.label,
    }
    if payload.scheduled_at is not None:
        fields["scheduled_at"] = payload.scheduled_at
    interview_id = await create_interview(
        journey_id=journey_id,
        # Never from the client: a round inherits the job's owner.
        profile_id=journey["profile_id"],
        **fields,
    )
    return {"interview_id": interview_id}


@router.patch("/journeys/{journey_id}/interviews/{interview_id}")
async def patch_journey_interview(
    journey_id: str, interview_id: str, payload: InterviewPatchPayload
) -> dict:
    owned = {i["interview_id"] for i in await list_interviews(journey_id)}
    if interview_id not in owned:
        raise HTTPException(404, "interview round not found")

    fields = payload.model_dump(exclude_unset=True)
    if "interview_type" in fields:
        fields["interview_type"] = _resolved_type(fields["interview_type"] or "")
    if "label" in fields and fields["label"] is None:
        fields["label"] = ""
    if fields:
        await update_interview(interview_id, **fields)
    return await _with_tracker_fields(await get_journey(journey_id))


class EventCreatePayload(BaseModel):
    occurred_at: float
    text: str = ""
    kind: str = "note"


class EventPatchPayload(BaseModel):
    occurred_at: float | None = None
    text: str | None = None
    kind: str | None = None


@router.post("/journeys/{journey_id}/events")
async def add_journey_event(journey_id: str, payload: EventCreatePayload) -> dict:
    if not await get_journey(journey_id):
        raise HTTPException(404, "journey not found")
    try:
        event_id = await add_event(
            journey_id=journey_id,
            occurred_at=payload.occurred_at,
            text=payload.text,
            kind=payload.kind,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"event_id": event_id}


@router.patch("/journeys/{journey_id}/events/{event_id}")
async def patch_journey_event(
    journey_id: str, event_id: str, payload: EventPatchPayload
) -> dict:
    owned = {e["event_id"] for e in await list_events(journey_id)}
    if event_id not in owned:
        raise HTTPException(404, "event not found")

    fields = payload.model_dump(exclude_unset=True)
    if fields.get("text") is None:
        fields.pop("text", None)
    # occurred_at is NOT NULL — an explicit null means "leave it", not "clear it".
    if fields.get("occurred_at") is None:
        fields.pop("occurred_at", None)
    if fields.get("kind") is None:
        fields.pop("kind", None)
    try:
        await update_event(event_id, **fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"events": await list_events(journey_id)}


@router.delete("/journeys/{journey_id}/events/{event_id}")
async def remove_journey_event(journey_id: str, event_id: str) -> dict:
    owned = {e["event_id"] for e in await list_events(journey_id)}
    if event_id not in owned:
        raise HTTPException(404, "event not found")
    await delete_event(event_id)
    return {"deleted": True}


class FeedbackPayload(BaseModel):
    # No `outcome`: it is derived from the job's dates when the row is written.
    model_config = {"extra": "forbid"}

    feedback_text: str = ""
    stage: str = "unknown"
    source: str = ""
    interview_ids: list[str] = []


@router.post("/journeys/{journey_id}/feedback")
async def add_journey_feedback(journey_id: str, payload: FeedbackPayload) -> dict:
    """Feedback that arrives mid-process, with no outcome attached — a recruiter's
    aside after a round. An outcome and its reason go through /outcome instead."""
    journey = await get_journey(journey_id)
    if not journey:
        raise HTTPException(404, "journey not found")

    known = {i["interview_id"] for i in await list_interviews(journey_id)}
    unknown = sorted(set(payload.interview_ids) - known)
    if unknown:
        raise HTTPException(400, f"interview round(s) not on this job: {unknown}")

    try:
        feedback_id = await add_feedback(
            journey_id=journey_id,
            # Never from the client: feedback inherits the job's owner.
            profile_id=journey["profile_id"],
            interview_ids=payload.interview_ids,
            stage=payload.stage,
            source=payload.source,
            feedback_text=payload.feedback_text,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"feedback_id": feedback_id}


# Which date each outcome writes. `withdrawn` lands on dropped_at: giving up on a
# silent application and pulling out of a live one are the same exit.
_OUTCOME_DATES = {
    "rejected": "rejected_at",
    "offer": "offer_at",
    "on_hold": "on_hold_at",
    "withdrawn": "dropped_at",
}


class OutcomePayload(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str
    date: float | None = None
    feedback_text: str = ""
    source: str = ""


@router.post("/journeys/{journey_id}/outcome")
async def log_journey_outcome(journey_id: str, payload: OutcomePayload) -> dict:
    """The date and what they said, written together.

    Splitting them is what let `job_feedback.outcome` drift from the dates: the
    outcome is snapshotted from `derive_status()` when the feedback row is written,
    so the date has to be there first. One call writes both, in that order.
    """
    journey = await get_journey(journey_id)
    if not journey:
        raise HTTPException(404, "journey not found")

    column = _OUTCOME_DATES.get(payload.kind)
    if not column:
        raise HTTPException(400, f"unknown outcome: {payload.kind!r}")

    await update_journey(journey_id, **{column: payload.date or time.time()})

    text = payload.feedback_text.strip()
    if text:
        try:
            await add_feedback(
                journey_id=journey_id,
                profile_id=journey["profile_id"],
                stage=infer_stage(await list_interviews(journey_id)),
                source=payload.source,
                feedback_text=text,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return await _with_tracker_fields(await get_journey(journey_id))


@router.delete("/journeys/{journey_id}/feedback/{feedback_id}")
async def remove_journey_feedback(journey_id: str, feedback_id: str) -> dict:
    owned = {e["feedback_id"] for e in await list_feedback(journey_id)}
    if feedback_id not in owned:
        raise HTTPException(404, "feedback not found")
    await delete_feedback(feedback_id)
    return {"deleted": True}


# What a re-application inherits: the posting and what you wrote about it. Dates,
# artifacts, rounds and feedback belong to the attempt that earned them.
_DUPLICATE_FIELDS = (
    "job_url",
    "job_title",
    "company_name",
    "location",
    "job_description",
    "company_description",
    "job_ad_language",
    "job_screenshot_path",
    "job_source_type",
    "notes",
)


@router.post("/journeys/{journey_id}/duplicate")
async def duplicate_journey(journey_id: str) -> dict:
    """Applying again to a company you have approached before.

    The strategies are deliberately not carried over — they were an argument for
    a different attempt. What the company told you last time still reaches the new
    cover letter anyway: `list_recent_feedback()` always includes same-company
    entries and sorts them first.
    """
    original = await get_journey(journey_id)
    if not original:
        raise HTTPException(404, "journey not found")

    new_id = await create_journey(
        profile_id=original["profile_id"],
        **{f: original[f] for f in _DUPLICATE_FIELDS if original.get(f)},
    )
    return await _with_tracker_fields(await get_journey(new_id))


@router.delete("/journeys/{journey_id}")
async def remove_journey(journey_id: str) -> dict:
    deleted = await delete_journey(journey_id)
    if not deleted:
        raise HTTPException(404, "journey not found")
    return {"deleted": True}


@router.get("/sessions/{session_id}/traces")
async def session_traces(session_id: str) -> dict:
    settings = load_settings()
    pricing = settings.model_pricing
    traces = await list_traces(session_id)
    enriched: list[dict] = []
    for t in traces:
        cost = _cost_for(t.get("model"), t["input_tokens"], t["output_tokens"], pricing)
        enriched.append({**t, "cost_usd": cost})
    return {"traces": enriched}


@router.get("/sessions/{session_id}/traces/{card_id}")
async def trace_detail(session_id: str, card_id: str) -> dict:
    trace = await get_trace(session_id, card_id)
    if not trace:
        raise HTTPException(404, "trace not found")
    settings = load_settings()
    trace["cost_usd"] = _cost_for(
        trace.get("model"), trace["input_tokens"], trace["output_tokens"], settings.model_pricing
    )
    return trace


@router.get("/graph/mermaid")
async def graph_mermaid(assistant_type: str = "cover_letter") -> dict:
    """Return the static LangGraph topology as a Mermaid source string."""
    from backend.agent.runner import GRAPH_BUILDERS

    builder = GRAPH_BUILDERS.get(assistant_type)
    if builder is None:
        raise HTTPException(400, f"unknown assistant_type: {assistant_type}")
    compiled = builder(checkpointer=None)
    mermaid = compiled.get_graph().draw_mermaid()
    return {"mermaid": mermaid}


class SettingsPayload(BaseModel):
    default_llm: LLMConfig
    task_llm_configs: dict[str, LLMConfig]
    model_pricing: dict[str, ModelPricing] = {}
    google_sheets_spreadsheet_id: str = ""


EDITABLE_FIELDS = {
    "language",
    "applicant_name",
    "cv_text",
    "candidate_profile",
    "job_url",
    "job_raw_text",
    "job_title",
    "company_name",
    "job_description",
    "company_description",
    "location",
    "job_source_type",
    "alignment_strategy",
    "inferred_role_context",
    "positioning_strategy",
    "cover_letter",
    "interview_context",
    "interview_briefing",
    "advisor_swot",
}


@router.get("/sessions/{session_id}/state")
async def get_session_state(session_id: str) -> dict:
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    values = await runner.get_state_values()
    if values is None:
        raise HTTPException(409, "session state not ready yet")
    editable = {k: values.get(k, "") for k in EDITABLE_FIELDS}
    versions_raw = values.get("cover_letter_versions") or []
    versions = [
        v.model_dump() if hasattr(v, "model_dump") else v
        for v in versions_raw
    ]
    return {
        "session_id": session_id,
        "phase": values.get("phase", ""),
        "paused": runner._paused,
        "fields": editable,
        "cover_letter_versions": versions,
        "best_version_id": values.get("best_version_id") or None,
    }


@router.patch("/sessions/{session_id}/state")
async def patch_session_state(session_id: str, patch: dict) -> dict:
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    clean = {k: v for k, v in patch.items() if k in EDITABLE_FIELDS}
    if not clean:
        raise HTTPException(400, "no editable fields in patch")
    ok = await runner.update_state_values(clean)
    if not ok:
        raise HTTPException(
            409,
            "session is currently running — wait until the assistant is waiting for your input, then retry.",
        )
    _FIELD_LABELS = {
        "applicant_name": "name", "cv_text": "CV", "candidate_profile": "candidate profile",
        "job_url": "job URL", "job_raw_text": "job ad", "job_title": "job title",
        "company_name": "company", "job_description": "job description",
        "company_description": "company description", "location": "location",
        "job_source_type": "job source", "alignment_strategy": "alignment strategy",
        "inferred_role_context": "role context", "positioning_strategy": "positioning strategy",
        "cover_letter": "cover letter", "language": "language",
        "interview_context": "interview context", "interview_briefing": "interview briefing",
        "advisor_swot": "SWOT analysis",
    }
    labels = [_FIELD_LABELS.get(k, k.replace("_", " ")) for k in clean]
    emit_message(session_id, f"I updated the {', '.join(labels)}.", role="user")
    return {"ok": True, "updated": list(clean.keys())}


@router.get("/sessions/{session_id}/exports/{kind}")
async def download_export(session_id: str, kind: str):
    """Stream a previously generated export file back to the user.

    Looks up the matching ExportResult on the running session's state. Prefers
    paths in the temp `career_assistant_exports` tree (those were written
    specifically for download) over folder-dump paths.
    """
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    values = await runner.get_state_values()
    if values is None:
        raise HTTPException(409, "session state not ready yet")

    raw_results = values.get("export_results") or []
    matches: list[str] = []
    for r in raw_results:
        r_kind = r.kind if hasattr(r, "kind") else r.get("kind")
        r_path = r.path if hasattr(r, "path") else r.get("path")
        if r_kind == kind and r_path:
            matches.append(r_path)

    if not matches:
        raise HTTPException(404, f"no {kind} export available")

    if kind == "sheets":
        return {"url": matches[-1]}

    # Prefer the temp-dir copy (written for download) if both exist.
    chosen = next(
        (p for p in reversed(matches) if "career_assistant_exports" in p),
        matches[-1],
    )
    p = Path(chosen)
    if not p.exists():
        raise HTTPException(410, "export file no longer on disk")
    return FileResponse(str(p), filename=p.name)


@router.post("/sessions/{session_id}/select-version")
async def select_cover_letter_version(session_id: str, body: dict) -> dict:
    version_id = body.get("version_id")
    if not version_id:
        raise HTTPException(400, "version_id required")
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    values = await runner.get_state_values()
    if values is None:
        raise HTTPException(409, "session state not ready yet")
    versions_raw = values.get("cover_letter_versions") or []
    matched = None
    for v in versions_raw:
        vid = v.version_id if hasattr(v, "version_id") else v.get("version_id")
        text = v.text if hasattr(v, "text") else v.get("text", "")
        if vid == version_id:
            matched = text
            break
    if matched is None:
        raise HTTPException(404, "version not found")
    ok = await runner.update_state_values({
        "best_version_id": version_id,
        "cover_letter": matched,
    })
    if not ok:
        raise HTTPException(409, "session is running — wait until paused")
    return {"ok": True, "best_version_id": version_id}


@router.get("/stats")
async def global_stats() -> dict:
    settings = load_settings()
    pricing = settings.model_pricing
    raw = await get_global_stats()

    sessions_by_type: dict[str, int] = raw["sessions_by_type"]
    trace_rows: list[tuple] = raw["trace_rows"]

    by_type: dict[str, dict] = {}
    for assistant_type, model, calls, input_tokens, output_tokens in trace_rows:
        entry = by_type.setdefault(
            assistant_type, {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        entry["llm_calls"] += calls
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["cost_usd"] += _cost_for(model, input_tokens, output_tokens, pricing)

    total_sessions = sum(sessions_by_type.values())
    total_calls = sum(e["llm_calls"] for e in by_type.values())
    total_in = sum(e["input_tokens"] for e in by_type.values())
    total_out = sum(e["output_tokens"] for e in by_type.values())
    total_cost = sum(e["cost_usd"] for e in by_type.values())

    return {
        "sessions_by_type": sessions_by_type,
        "totals": {
            "sessions": total_sessions,
            "llm_calls": total_calls,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cost_usd": total_cost,
        },
        "by_assistant_type": by_type,
    }


@router.get("/settings")
async def get_settings() -> dict:
    s = load_settings()
    return {
        "default_llm": s.default_llm.model_dump(exclude={"api_key"}),
        "task_llm_configs": {k: v.model_dump(exclude={"api_key"}) for k, v in s.task_llm_configs.items()},
        "model_pricing": {k: v.model_dump() for k, v in s.model_pricing.items()},
        "known_tasks": KNOWN_TASKS,
        "google_sheets_spreadsheet_id": s.google_sheets_spreadsheet_id,
    }


@router.put("/settings")
async def update_settings(payload: SettingsPayload) -> dict:
    s = load_settings()
    s.default_llm = payload.default_llm
    s.task_llm_configs = {
        k: v
        for k, v in payload.task_llm_configs.items()
        if (v.provider and v.model_name) or v.max_tokens is not None
    }
    s.model_pricing = {k: v for k, v in payload.model_pricing.items() if k.strip()}
    s.google_sheets_spreadsheet_id = payload.google_sheets_spreadsheet_id
    save_settings(s)
    return {"ok": True}


@router.get("/profiles/{profile_id}/playbook")
async def profile_playbook(profile_id: str) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    return await get_playbook(profile_id)


@router.patch("/profiles/{profile_id}/playbook")
async def patch_playbook(profile_id: str, payload: dict) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    await upsert_playbook(profile_id, payload)
    return {"ok": True}


@router.delete("/profiles/{profile_id}/playbook/{category}/{index}")
async def delete_playbook_item(profile_id: str, category: str, index: int) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    removed = await remove_playbook_item(profile_id, category, index)
    if not removed:
        raise HTTPException(404, "playbook item not found")
    return {"ok": True}


@router.get("/profiles/{profile_id}/suggestions")
async def profile_suggestions(profile_id: str) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    return {
        "suggestions": await list_pending(profile_id),
        "pending_count": await count_pending(profile_id),
    }


@router.post("/profiles/{profile_id}/suggestions/{suggestion_id}/approve")
async def approve_profile_suggestion(profile_id: str, suggestion_id: int) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    result = await approve_suggestion(suggestion_id)
    if not result:
        raise HTTPException(404, "suggestion not found or not pending")
    if result["profile_id"] != profile_id:
        raise HTTPException(404, "suggestion not found for this profile")
    return {"ok": True, "suggestion": result}


@router.post("/profiles/{profile_id}/suggestions/{suggestion_id}/reject")
async def reject_profile_suggestion(profile_id: str, suggestion_id: int) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    ok = await reject_suggestion(suggestion_id)
    if not ok:
        raise HTTPException(404, "suggestion not found or not pending")
    return {"ok": True}
