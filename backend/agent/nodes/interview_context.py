"""Collect any information the company shared about the upcoming interview."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState


async def interview_context_node(state: ApplicationState) -> dict:
    sid = state.session_id
    emit_message(
        sid,
        "Before I prepare your briefing, paste anything the company has shared about the "
        "upcoming interview — round, format, interviewer names or roles, focus areas, "
        "instructions from HR, etc. Reply `none` if you haven't been told anything specific.",
        key="interview_context:prompt",
    )
    reply = interrupt({"kind": "interview_context"})
    text = (reply or "").strip() if isinstance(reply, str) else ""
    if text.lower() == "none":
        text = ""
    return {"interview_context": text, "phase": "interview_briefing"}
