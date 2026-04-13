"""Generate a SWOT summary on demand from the advisor transcript + profile."""

from __future__ import annotations

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm


def _render_transcript(state: ApplicationState) -> str:
    lines: list[str] = []
    for turn in state.advisor_transcript:
        speaker = "Candidate" if turn.role == "user" else "Advisor"
        lines.append(f"{speaker}: {turn.content}")
    return "\n\n".join(lines) if lines else "(no conversation yet)"


async def swot_summary_node(state: ApplicationState) -> dict:
    sid = state.session_id

    aid = action_start(sid, "advisor_swot", "Synthesising SWOT")
    system = load_system_prompt("career_advisor_swot")
    user = render_user_prompt(
        "career_advisor_swot",
        candidate_profile=state.candidate_profile,
        cv_content=state.cv_text,
        transcript=_render_transcript(state),
    )
    result = await call_llm(
        task="career_advisor_swot",
        system=system,
        user=user,
        session_id=sid,
    )
    action_finish(sid, aid)

    emit_message(sid, "Here's a SWOT synthesis based on our conversation:")
    emit_message(sid, result.text)
    emit_message(
        sid,
        "Want to keep exploring? Ask me anything, type `/swot` for a fresh summary later, "
        "or `done` to wrap up.",
    )

    return {"advisor_swot": result.text, "phase": "advisor_chat"}
