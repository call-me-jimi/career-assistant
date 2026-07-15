"""Announce the inferred job source type (direct vs recruiter) and let the user correct it."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState


def _label(source: str) -> str:
    return "recruiter/agency" if source == "recruiter" else "direct company"


async def classify_flow_node(state: ApplicationState) -> dict:
    sid = state.session_id
    inferred = state.job_source_type or "direct"
    emit_message(
        sid,
        f"This looks like a **{_label(inferred)}** posting — I'll tailor the strategy accordingly. "
        "If that's not right, tell me; otherwise we'll continue.",
        key="classify_flow:confirm",
    )
    reply = interrupt({"kind": "classify_flow_confirm", "inferred": inferred})

    text = (reply or "").strip().lower() if isinstance(reply, str) else ""
    if "recru" in text or "agenc" in text:
        source = "recruiter"
    elif "direct" in text or "company" in text:
        source = "direct"
    else:
        source = inferred

    if source != inferred:
        emit_message(sid, f"Got it — treating this as a **{_label(source)}** application.")
    return {"job_source_type": source, "phase": "strategy"}
