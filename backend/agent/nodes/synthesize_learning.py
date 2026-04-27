"""End-of-session learning synthesis for the cover-letter flow.

Runs once when a cover-letter session terminates:
1. Persists the completed application to `application_records` + `application_hm_iterations`.
2. Calls one LLM to reflect on this session + recent history and produce an updated
   per-profile playbook and (optionally) a proposed edit to `candidate_profile`.
3. Upserts the playbook. Inserts a suggestion row if the LLM produced one.
4. Hands off a `pending_suggestion` dict on state when the suggestion is high-confidence,
   so `review_learned_suggestion` can surface it inline.

No-op unless `assistant_type == "cover_letter"`, `learning_enabled`, a profile is set,
and a cover letter was actually produced.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.config import load_settings
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm, extract_json
from backend.storage.applications import (
    insert_application_record,
    insert_hm_iteration,
    list_recent_applications,
)
from backend.storage.playbook import get_playbook, upsert_playbook
from backend.storage.suggestions import (
    approve_suggestion,
    insert_suggestion,
    reject_suggestion,
)


def _should_run(state: ApplicationState, settings) -> bool:
    if state.assistant_type != "cover_letter":
        return False
    if not settings.learning_enabled:
        return False
    if not state.profile_id:
        return False
    if not state.cover_letter:
        return False
    return True


def _final_hm_feedback(state: ApplicationState) -> dict[str, Any] | None:
    for v in reversed(state.cover_letter_versions):
        if v.hm_feedback:
            return v.hm_feedback
    return None


def _hm_iteration_rows(state: ApplicationState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for v in state.cover_letter_versions:
        if not v.hm_feedback:
            continue
        fb = v.hm_feedback
        rows.append(
            {
                "iteration": v.iteration,
                "score": v.hm_score,
                "strengths": fb.get("strengths") or [],
                "weaknesses": fb.get("weaknesses") or [],
                "suggestions": fb.get("suggestions") or [],
            }
        )
    return rows


async def synthesize_learning_node(state: ApplicationState) -> dict:
    settings = load_settings()
    if not _should_run(state, settings):
        return {}

    sid = state.session_id
    aid = action_start(sid, "synthesize_learning", "Learning from this session")

    try:
        versions = state.cover_letter_versions
        initial_cl = versions[0].text if versions else ""
        final_cl = state.cover_letter
        hm_final = _final_hm_feedback(state)
        iterations = _hm_iteration_rows(state)

        app_id = await insert_application_record(
            profile_id=state.profile_id,
            session_id=sid,
            job_title=state.job_title,
            company_name=state.company_name,
            job_source_type=state.job_source_type or "",
            initial_cl=initial_cl,
            final_cl=final_cl,
            revision_count=len(state.revision_feedback),
            hm_feedback_final=hm_final,
            revision_feedback=list(state.revision_feedback),
        )
        for row in iterations:
            await insert_hm_iteration(application_record_id=app_id, **row)

        current_playbook = await get_playbook(state.profile_id)
        recent = await list_recent_applications(
            state.profile_id, limit=settings.synthesis_window_n + 1
        )
        recent_prior = [r for r in recent if r["id"] != app_id][: settings.synthesis_window_n]

        this_session = {
            "job_title": state.job_title,
            "company_name": state.company_name,
            "initial_cl": initial_cl,
            "final_cl": final_cl,
            "revision_count": len(state.revision_feedback),
            "revision_feedback": list(state.revision_feedback),
            "hm_iterations": iterations,
        }

        system = load_system_prompt("synthesize_learning")
        user = render_user_prompt(
            "synthesize_learning",
            current_playbook=json.dumps(current_playbook, indent=2, default=str),
            current_candidate_profile=state.candidate_profile or "",
            this_session_signals=json.dumps(this_session, indent=2, default=str),
            recent_applications=json.dumps(recent_prior, indent=2, default=str),
        )
        result = await call_llm(
            task="synthesize_learning",
            system=system,
            user=user,
            session_id=sid,
        )

        try:
            payload = extract_json(result.text)
        except Exception:
            payload = {}

        playbook_out = payload.get("playbook") if isinstance(payload, dict) else None
        suggestion_out = payload.get("suggestion") if isinstance(payload, dict) else None

        if isinstance(playbook_out, dict):
            await upsert_playbook(state.profile_id, playbook_out)

        pending: dict[str, Any] | None = None
        if isinstance(suggestion_out, dict):
            diff = suggestion_out.get("diff") or {}
            before = diff.get("before")
            after = diff.get("after")
            if isinstance(before, str) and isinstance(after, str) and after.strip() and after != before:
                confidence = int(suggestion_out.get("confidence") or 1)
                rationale = diff.get("rationale") or ""
                suggestion_id = await insert_suggestion(
                    profile_id=state.profile_id,
                    diff={"before": before, "after": after, "rationale": rationale},
                    confidence=confidence,
                    source_application_ids=[app_id],
                )
                if confidence >= settings.inline_surface_threshold:
                    pending = {
                        "suggestion_id": suggestion_id,
                        "before": before,
                        "after": after,
                        "rationale": rationale,
                        "confidence": confidence,
                    }

        action_finish(sid, aid)
    except Exception as exc:
        action_finish(sid, aid, status="error")
        emit_message(
            sid,
            f"(Learning pass skipped: {exc})",
            key=f"synthesize:error:{sid}",
        )
        return {}

    if pending is None:
        return {}
    return {"pending_suggestion": pending}


async def review_learned_suggestion_node(state: ApplicationState) -> dict:
    pending = state.pending_suggestion
    if not pending or not isinstance(pending, dict):
        return {}

    sid = state.session_id
    suggestion_id = pending.get("suggestion_id")
    rationale = pending.get("rationale") or ""
    confidence = int(pending.get("confidence") or 1)

    emit_message(
        sid,
        (
            f"I noticed a consistent pattern across your recent cover letters "
            f"(supported by **{confidence}** independent signals). "
            f"I'd like to propose this tweak to your profile statement:\n\n"
            f"> {rationale}\n\n"
            "Reply `yes` to apply it now, `no` to discard it, "
            "or anything else to leave it pending in your profile's Suggestions inbox."
        ),
        key=f"synthesize:inline:{suggestion_id}",
    )
    reply = interrupt({"kind": "profile_suggestion", "suggestion": pending})
    reply_text = (reply or "").strip().lower() if isinstance(reply, str) else ""

    if reply_text.startswith("y"):
        applied = await approve_suggestion(int(suggestion_id)) if suggestion_id else None
        if applied:
            emit_message(
                sid,
                "Applied. Your profile statement has been updated.",
                key=f"synthesize:applied:{suggestion_id}",
            )
            return {"candidate_profile": pending.get("after") or state.candidate_profile, "pending_suggestion": None}
        emit_message(
            sid,
            "Couldn't apply — the suggestion may already have been resolved.",
            key=f"synthesize:apply_failed:{suggestion_id}",
        )
        return {"pending_suggestion": None}

    if reply_text.startswith("n"):
        if suggestion_id:
            await reject_suggestion(int(suggestion_id))
        emit_message(
            sid,
            "Rejected. I won't surface this suggestion again.",
            key=f"synthesize:rejected:{suggestion_id}",
        )
        return {"pending_suggestion": None}

    emit_message(
        sid,
        "Left pending — you can review it any time on your profile page.",
        key=f"synthesize:pending:{suggestion_id}",
    )
    return {"pending_suggestion": None}
