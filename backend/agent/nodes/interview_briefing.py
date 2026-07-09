"""Single-pass interview briefing generation."""

from __future__ import annotations

from backend.agent.interrupts import action_finish, action_start
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm
from backend.llm.translate import with_language_directive


async def interview_briefing_node(state: ApplicationState) -> dict:
    sid = state.session_id

    aid = action_start(sid, "interview_briefing", "Preparing your interview briefing")
    system = load_system_prompt("interview_briefing")
    user = render_user_prompt(
        "generate_interview_briefing",
        company_name=state.company_name,
        job_title=state.job_title,
        location=state.location,
        interview_context=state.interview_context or "",
        job_description=state.job_description,
        company_description=state.company_description,
        candidate_profile=state.candidate_profile,
        cv_content=state.cv_text,
        alignment_strategy=state.alignment_strategy or state.inferred_role_context or "",
        coaching_history=state.coaching_history,
        cover_letter=state.cover_letter or "",
        positioning_strategy=state.positioning_strategy or "",
        previous_briefing=state.interview_briefing or "",
    )
    user = with_language_directive(user, state.language)
    result = await call_llm(
        task="interview_briefing",
        system=system,
        user=user,
        session_id=sid,
    )
    action_finish(sid, aid)

    briefing = result.text
    if result.truncated:
        briefing += "\n\n---\n⚠️ *Output truncated — token limit reached. Ask me to continue if needed.*"

    initial_version = {"iteration": 0, "text": briefing}
    return {
        "interview_briefing": briefing,
        "interview_briefing_versions": [initial_version],
        "phase": "interview_review",
    }
