"""CV intake: either reuse a saved profile or ask the user to upload a PDF."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm
from backend.storage.profiles import get_profile, save_profile


async def cv_intake_node(state: ApplicationState) -> dict:
    sid = state.session_id

    if state.profile_id:
        profile = await get_profile(state.profile_id)
        if profile:
            # Greeting already informed the user — just load the data silently.
            return {
                "cv_text": profile["cv_text"],
                "candidate_profile": profile["candidate_profile"] if isinstance(profile["candidate_profile"], str) else str(profile["candidate_profile"]),
                "profile_reused": True,
                "phase": "collect_job",
            }

    emit_message(
        sid,
        "Please upload your CV as a PDF so I can build a candidate profile.",
        key="cv_intake:upload_prompt",
    )
    payload = interrupt({"kind": "upload_cv"})
    cv_text = (payload or {}).get("cv_text", "") if isinstance(payload, dict) else ""
    if not cv_text:
        emit_message(sid, "No CV received — I'll continue without one, but the cover letter may be less targeted.")
        return {"phase": "collect_job"}

    emit_message(
        sid,
        "Got your CV — I'll build a candidate profile from it. Would you like to "
        "save that profile for future sessions?\n\n"
        "Give it a short label (e.g. `Backend focus`, `Data science`) or reply `no` to skip saving.",
        key="cv_intake:label_prompt",
    )
    label_reply = interrupt({"kind": "profile_label"})
    label = (label_reply or "").strip() if isinstance(label_reply, str) else ""

    action_id = action_start(sid, "candidate_profile", "Extracting candidate profile from your CV")
    system = load_system_prompt("extract_candidate_profile_from_cv")
    user = render_user_prompt("extract_candidate_profile_from_cv", cv_content=cv_text)
    result = await call_llm(
        task="candidate_profile",
        system=system,
        user=user,
        session_id=sid,
    )
    action_finish(sid, action_id)

    if label.lower() in {"no", "skip", "don't save", "dont save"}:
        emit_message(sid, "Okay — using this profile for this session only, not saving it.")
        return {
            "cv_text": cv_text,
            "candidate_profile": result.text,
            "phase": "collect_job",
        }

    default_label = state.applicant_name or "Applicant"
    profile_name = label or default_label
    pid = await save_profile(
        name=profile_name,
        applicant_name=state.applicant_name or None,
        cv_text=cv_text,
        candidate_profile=result.text,
    )
    emit_message(sid, f"Saved profile as **{profile_name}**.")
    return {
        "profile_id": pid,
        "cv_text": cv_text,
        "candidate_profile": result.text,
        "phase": "collect_job",
    }
