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


async def greeting_node(state: ApplicationState) -> dict:
    sid = state.session_id
    details_url = f"/session/details?id={sid}"
    emit_message(
        sid,
        "Hi! I'm your Personal Application Assistant. I'll walk you through creating a "
        "tailored cover letter and preparing for application questions.\n\n"
        f"You can review and edit all extracted information at any time on the "
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
        emit_message(
            sid,
            f"Welcome back, {applicant_name}! I'll use your saved profile — no need to upload a CV again.\n\n"
            "Now share the job you're applying for. Paste the URL of the posting, or the job description text directly.",
        )
    else:
        emit_message(sid, f"Great to meet you, {applicant_name}!")
    return update
