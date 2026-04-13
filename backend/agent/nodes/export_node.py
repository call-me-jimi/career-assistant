"""Final export node: ask the user what to export, run the chosen exporters."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import (
    action_finish,
    action_start,
    emit_export_ready,
    emit_message,
)
from backend.agent.state import ApplicationState, ExportResult
from backend.storage.traces import list_traces
from backend.tools import exporters


async def export_node(state: ApplicationState) -> dict:
    sid = state.session_id
    artifact_hint = {
        "cover_letter": "your cover letter and Q&A",
        "interview_prep": "your interview briefing",
        "career_advisor": "the conversation and (if you generated one) your SWOT",
    }.get(state.assistant_type, "your session")
    emit_message(
        sid,
        f"Time to export {artifact_hint}. Which formats would you like?\n\n"
        "Reply with any combination of: `pdf`, `md`, `json`, `sheets`, or `all`. "
        "Say `none` to skip.",
        key="export:prompt",
    )
    reply = interrupt({"kind": "export_choice"})
    text = (reply or "").strip().lower() if isinstance(reply, str) else ""
    if not text or text == "none":
        emit_message(sid, "Skipped export — you can always come back to this.")
        return {"phase": "done"}

    selection = (
        ["pdf", "md", "json", "sheets"] if text == "all" else [w.strip() for w in text.split() if w.strip()]
    )

    state_dict = state.model_dump(mode="json")
    results: list[ExportResult] = list(state.export_results)

    for kind in selection:
        aid = action_start(sid, f"export_{kind}", f"Exporting {kind}")
        try:
            if kind == "pdf":
                path = exporters.export_pdf(state_dict)
            elif kind == "md":
                path = exporters.export_markdown(state_dict)
            elif kind == "json":
                traces = await list_traces(sid)
                path = exporters.export_json(state_dict, traces)
            elif kind == "sheets":
                path = exporters.export_google_sheets(state_dict)
            else:
                action_finish(sid, aid, status="error")
                emit_message(sid, f"Unknown export kind: {kind}")
                continue
            action_finish(sid, aid)
            results.append(ExportResult(kind=kind, path=path))
            emit_export_ready(sid, kind, path)
            emit_message(sid, f"✓ {kind} → `{path}`")
        except Exception as exc:
            action_finish(sid, aid, status="error")
            emit_message(sid, f"✗ {kind} export failed: {exc}")

    if state.assistant_type == "cover_letter":
        emit_message(
            sid,
            "Anything else you'd like to work on? Reply `yes` to go back to questions, "
            "or `no` to wrap up.",
            key=f"export:followup:{len(results)}",
        )
        follow = interrupt({"kind": "post_export"})
        follow_text = (follow or "").strip().lower() if isinstance(follow, str) else ""
        if follow_text.startswith("y"):
            return {"export_results": results, "phase": "qa_menu"}

    emit_message(sid, "All done — good luck!")
    return {"export_results": results, "phase": "done"}
