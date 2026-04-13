"""Greeting node: introduce, ask name, offer saved profiles."""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState
from backend.storage.profiles import list_profiles


def _format_saved_at(ts: float | int | None) -> str:
    if not ts:
        return "unknown"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


_INTRO_BY_ASSISTANT = {
    "cover_letter": (
        "Hi! I'm your Personal Career Assistant — cover letter mode. I'll walk you through "
        "creating a tailored cover letter and preparing for application questions."
    ),
    "interview_prep": (
        "Hi! I'm your Interview Prep assistant. I'll prepare a tailored briefing for "
        "your upcoming interview — likely questions, positioning, stories to rehearse, "
        "and how to handle the most probable hiring concerns."
    ),
    "career_advisor": (
        "Hi! I'm your Career Advisor. We'll have an open conversation about your "
        "experience so you can clarify your strengths, spot weaknesses, and sharpen how "
        "you talk about your career. You can ask for a SWOT summary at any time."
    ),
}


async def greeting_node(state: ApplicationState) -> dict:
    sid = state.session_id
    details_url = f"/session/details?id={sid}"
    intro = _INTRO_BY_ASSISTANT.get(state.assistant_type, _INTRO_BY_ASSISTANT["cover_letter"])
    emit_message(
        sid,
        f"{intro}\n\n"
        f"You can review and edit the information we gather on the "
        f"[Details page]({details_url}).\n\n"
        "First — what's your name?",
        key="greeting:welcome",
    )

    profiles = (await list_profiles())[:10]
    if profiles:
        lines = [
            f"{i}. **{p['name']}** — saved {_format_saved_at(p.get('updated_at') or p.get('created_at'))}"
            for i, p in enumerate(profiles, start=1)
        ]
        emit_message(
            sid,
            "You have saved profiles:\n\n"
            + "\n".join(lines)
            + "\n\n_Reply with the number (e.g. `1`) to reuse a profile and skip the CV upload._",
            key="greeting:profiles_hint",
        )

    answer = interrupt({"kind": "ask_name", "profiles": profiles})
    raw = (answer or "").strip()

    matched_profile = None
    if profiles and raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(profiles):
            matched_profile = profiles[idx - 1]

    applicant_name = matched_profile["name"] if matched_profile else (raw or "Applicant")

    update: dict = {"applicant_name": applicant_name, "phase": "cv_intake"}
    if matched_profile:
        update["profile_id"] = matched_profile["profile_id"]
        if state.assistant_type == "career_advisor":
            next_hint = "We can dive straight into the conversation."
        else:
            next_hint = (
                "Now share the job you're applying for. Paste the URL of the posting, "
                "or the job description text directly."
            )
        emit_message(
            sid,
            f"Welcome back, {applicant_name}! I'll use your saved profile — no need to upload a CV again.\n\n"
            f"{next_hint}",
        )
    else:
        emit_message(sid, f"Great to meet you, {applicant_name}!")
    return update
