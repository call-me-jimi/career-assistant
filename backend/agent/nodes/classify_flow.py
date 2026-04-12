"""Ask the user whether this is a direct company posting or a recruiter ad."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState


async def classify_flow_node(state: ApplicationState) -> dict:
    sid = state.session_id
    emit_message(
        sid,
        "Is this a direct posting by the hiring company, or from a recruiter/agency?",
        key="classify_flow:prompt",
    )
    reply = interrupt({"kind": "classify_flow"})
    text = (reply or "").strip().lower() if isinstance(reply, str) else ""
    if text.startswith("rec"):
        source = "recruiter"
    else:
        source = "direct"
    emit_message(sid, f"Noted — I'll tailor the strategy for a **{source}** application.")
    return {"job_source_type": source, "phase": "strategy"}
