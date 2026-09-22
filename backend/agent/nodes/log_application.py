"""Cover Letter only: what the tracker should record alongside the assets.

Asked before `export_node` writes anything, because both answers also shape the
spreadsheet row `export_sheets_node` appends — the notes fill its Notes column,
the submission its Status and Submission columns.
"""

from __future__ import annotations

import time

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState
from backend.storage.journeys import update_journey

# Typed answers that mean "nothing to record" rather than a note.
_NO_NOTES = {"", "-", "n", "no", "none", "nothing", "skip"}


async def log_application_node(state: ApplicationState) -> dict:
    """Ask once, even when the export loop comes back around for a second pass."""
    if state.application_logged:
        return {}

    sid = state.session_id
    emit_message(
        sid,
        "Before I put the files together — anything to note about this application?\n\n"
        "e.g. `applied on their job page, salary expectation 120k`, or "
        "`applied via EasyApply on LinkedIn, no further details`.\n\n"
        "It goes on the application in your tracker and into the Notes column of "
        "your sheet. Reply `skip` if there's nothing.",
        key="log_application:notes",
    )
    notes_reply = interrupt({"kind": "application_notes"})
    notes = notes_reply.strip() if isinstance(notes_reply, str) else ""
    if notes.lower() in _NO_NOTES:
        notes = ""

    emit_message(
        sid,
        "Have you submitted this application already? `yes` records today as the "
        "submission date, `no` leaves it as a draft you can date later.",
        key="log_application:submitted",
    )
    submitted_reply = interrupt({"kind": "application_submitted"})
    submitted = (
        submitted_reply.strip().lower().startswith("y")
        if isinstance(submitted_reply, str)
        else False
    )
    applied_at = time.time() if submitted else None

    # Nothing may interrupt below this point: LangGraph replays the node body
    # from the top on resume, so the write sits after the last interrupt.
    fields: dict[str, object] = {}
    if notes:
        fields["notes"] = notes
    if applied_at:
        fields["applied_at"] = applied_at
    if state.journey_id and fields:
        await update_journey(state.journey_id, **fields)

    if applied_at:
        emit_message(sid, "✓ Noted, and dated as submitted today.")
    elif notes:
        emit_message(sid, "✓ Noted.")

    return {
        "application_notes": notes,
        "applied_at": applied_at,
        "application_logged": True,
        "phase": "log_application",
    }
