"""Offer to switch the session output language when the job ad is in another language."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message, emit_state
from backend.agent.state import ApplicationState


async def language_switch_node(state: ApplicationState) -> dict:
    sid = state.session_id
    detected = (state.job_ad_language or "").strip()
    if not detected or detected.lower() == state.language.lower():
        return {}

    emit_message(
        sid,
        f"The job ad is in **{detected}**, but your current output language is **{state.language}**. "
        f"Would you like to switch the output language to **{detected}**?",
        key="extract_info:language_switch",
    )
    reply = interrupt({"kind": "language_switch", "detected_language": detected, "current_language": state.language})
    answered_yes = (
        (isinstance(reply, str) and reply.strip().lower() in {"yes", "y", "switch", "ja", "oui", "si", "sí"})
        or (isinstance(reply, dict) and reply.get("switch"))
    )
    if answered_yes:
        # Past the interrupt, so this runs once — the session header reads it to
        # stay honest about the language the graph is actually generating in.
        emit_state(sid, {"language": detected})
        return {"language": detected}
    return {}
