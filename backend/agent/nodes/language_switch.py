"""Offer to switch the session output language when the source material is in another language."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message, emit_state
from backend.agent.state import ApplicationState

_YES = {"yes", "y", "switch", "ja", "oui", "si", "sí"}


def _offer_switch(state: ApplicationState, detected: str, *, source: str, key: str) -> dict:
    """Ask whether to switch the output language to `detected`.

    Returns the state update. Nothing is asked when the language matches the
    session's, or when this session already offered that same language — a
    German job ad followed by a German interview invitation is one question.
    """
    sid = state.session_id
    detected = (detected or "").strip()
    if not detected or detected.lower() in (state.language.lower(), state.language_offered.lower()):
        return {}

    emit_message(
        sid,
        f"{source} is in **{detected}**, but your current output language is **{state.language}**. "
        f"Would you like to switch the output language to **{detected}**?",
        key=key,
    )
    reply = interrupt({"kind": "language_switch", "detected_language": detected, "current_language": state.language})
    answered_yes = (
        (isinstance(reply, str) and reply.strip().lower() in _YES)
        or (isinstance(reply, dict) and reply.get("switch"))
    )
    if answered_yes:
        # Past the interrupt, so this runs once — the session header reads it to
        # stay honest about the language the graph is actually generating in.
        emit_state(sid, {"language": detected})
        return {"language": detected, "language_offered": detected}
    return {"language_offered": detected}


async def language_switch_node(state: ApplicationState) -> dict:
    return _offer_switch(
        state,
        state.job_ad_language,
        source="The job ad",
        key="extract_info:language_switch",
    )


async def interview_language_switch_node(state: ApplicationState) -> dict:
    return _offer_switch(
        state,
        state.interview_context_language,
        source="The interview details you pasted",
        key="interview_context:language_switch",
    )
