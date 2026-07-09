"""Show the interview briefing, loop revisions until accepted."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt
from backend.llm.service import call_llm
from backend.llm.translate import with_language_directive
from backend.storage.journeys import update_journey


async def interview_review_node(state: ApplicationState) -> dict:
    sid = state.session_id
    iteration = len(state.interview_briefing_versions)

    emit_message(
        sid,
        state.interview_briefing or "(no briefing produced)",
        key=f"interview_review:body:{iteration}",
        localized=True,
    )
    emit_message(
        sid,
        "Here's your interview briefing. Reply `accept` to keep it, or describe any "
        "revisions you'd like (e.g. \"shorter\", \"more on the technical stack\", "
        "\"emphasize the EU operations\").",
        key=f"interview_review:prompt:{iteration}",
    )
    reply = interrupt({"kind": "interview_review", "briefing": state.interview_briefing})

    text = (reply or "").strip() if isinstance(reply, str) else ""
    if not text or text.lower() in {"accept", "ok", "looks good", "yes"}:
        if state.journey_id and state.interview_briefing:
            try:
                await update_journey(state.journey_id, interview_briefing=state.interview_briefing)
            except Exception:
                pass
        return {"phase": "interview_menu"}

    aid = action_start(sid, "refine_interview_briefing", "Applying your revisions")
    chat_system = load_system_prompt("chat")
    user = (
        f"Here is the current interview briefing:\n\n{state.interview_briefing}\n\n"
        f"Please revise it based on this feedback: {text}\n\n"
        "Return only the revised briefing."
    )
    user = with_language_directive(user, state.language)
    result = await call_llm(
        task="refine_interview_briefing",
        system=chat_system,
        user=user,
        session_id=sid,
    )
    action_finish(sid, aid)

    briefing = result.text
    if result.truncated:
        briefing += "\n\n---\n⚠️ *Output truncated — token limit reached. Ask me to continue if needed.*"

    new_version = {"iteration": iteration, "text": briefing}
    feedback_entry = {"iteration": iteration, "freetext": text}

    return {
        "interview_briefing": briefing,
        "interview_briefing_versions": state.interview_briefing_versions + [new_version],
        "interview_revision_feedback": state.interview_revision_feedback + [feedback_entry],
        "phase": "interview_review",
    }
