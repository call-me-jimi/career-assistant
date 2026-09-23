"""Collect any information the company shared about the upcoming interview."""

from __future__ import annotations

import logging

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm

log = logging.getLogger("assistant.interview_context")


async def _detect_language(sid: str, text: str) -> str:
    """English name of the language `text` is written in, or "" when unsure."""
    try:
        result = await call_llm(
            task="detect_language",
            system=load_system_prompt("detect_language"),
            user=render_user_prompt("detect_language", text=text),
            session_id=sid,
        )
    except Exception:
        log.warning("language detection failed — keeping the session language")
        return ""

    answer = (result.text.strip().splitlines() or [""])[0].strip(" `.\"'")
    if answer.lower() == "unknown" or len(answer) > 30:
        return ""
    return answer


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
    # Detection sits after the interrupt so it costs one call, not one per resume pass.
    language = await _detect_language(sid, text) if text else ""
    return {
        "interview_context": text,
        "interview_context_language": language,
        "phase": "interview_briefing",
    }
