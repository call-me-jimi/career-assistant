"""Final export node: ask the user what to export, run the chosen exporters."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

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


def _temp_export_dir(session_id: str) -> Path:
    return (
        Path(tempfile.gettempdir())
        / "career_assistant_exports"
        / session_id
        / time.strftime("%Y.%m.%d")
    )


async def export_node(state: ApplicationState) -> dict:
    sid = state.session_id
    artifact_hint = {
        "cover_letter": "your cover letter and Q&A",
        "interview_prep": "your interview briefing",
        "career_advisor": "the conversation and (if you generated one) your SWOT",
    }.get(state.assistant_type, "your session")

    delivery = state.export_delivery
    if state.assistant_type == "interview_prep" and not delivery:
        emit_message(
            sid,
            "Where should I put it? Reply `download` (link in chat — recommended), "
            "`folder` (save to your Applications folder), or `both`.",
            key=f"export:delivery:{len(state.export_results)}",
        )
        delivery_reply = interrupt({"kind": "export_delivery"})
        delivery_text = (
            (delivery_reply or "").strip().lower() if isinstance(delivery_reply, str) else ""
        )
        if delivery_text in {"download", "folder", "both"}:
            delivery = delivery_text
        else:
            delivery = "download"
            emit_message(sid, "Defaulting to **download** (link in chat).")

    targets: list[Path | None]
    if state.assistant_type == "interview_prep":
        if delivery == "folder":
            targets = [None]  # configured Applications folder
        elif delivery == "both":
            targets = [_temp_export_dir(sid), None]
        else:  # "download"
            targets = [_temp_export_dir(sid)]
    else:
        targets = [None]
        delivery = delivery or "folder"

    emit_message(
        sid,
        f"Time to export {artifact_hint}. Which formats would you like?\n\n"
        "Reply with any combination of: `pdf`, `md`, `json`, `sheets`, or `all`. "
        "Say `none` to skip.",
        key=f"export:prompt:{len(state.export_results)}",
    )
    reply = interrupt({"kind": "export_choice"})
    text = (reply or "").strip().lower() if isinstance(reply, str) else ""
    if not text or text == "none":
        emit_message(sid, "Skipped export — you can always come back to this.")
        return {"phase": "post_export", "export_delivery": delivery}

    selection = (
        ["pdf", "md", "json", "sheets"] if text == "all" else [w.strip() for w in text.split() if w.strip()]
    )

    state_dict = state.model_dump(mode="json")
    results: list[ExportResult] = list(state.export_results)

    for kind in selection:
        per_kind_targets = [None] if kind == "sheets" else targets
        for target in per_kind_targets:
            label_suffix = "" if target is None else " (download)"
            aid = action_start(sid, f"export_{kind}", f"Exporting {kind}{label_suffix}")
            try:
                if kind == "pdf":
                    path = exporters.export_pdf(state_dict, target_dir=target)
                elif kind == "md":
                    path = exporters.export_markdown(state_dict, target_dir=target)
                elif kind == "json":
                    traces = await list_traces(sid)
                    path = exporters.export_json(state_dict, traces, target_dir=target)
                elif kind == "sheets":
                    path = exporters.export_google_sheets(state_dict)
                else:
                    action_finish(sid, aid, status="error")
                    emit_message(sid, f"Unknown export kind: {kind}")
                    continue
                action_finish(sid, aid)
                results.append(ExportResult(kind=kind, path=path))
                if target is not None:
                    emit_export_ready(sid, kind, path)
                    emit_message(sid, f"✓ {kind} ready to download.")
                else:
                    emit_message(sid, f"✓ {kind} → `{path}`")
            except Exception as exc:
                action_finish(sid, aid, status="error")
                emit_message(sid, f"✗ {kind} export failed: {exc}")

    return {
        "export_results": results,
        "phase": "post_export",
        "export_delivery": delivery,
    }


async def post_export_node(state: ApplicationState) -> dict:
    sid = state.session_id
    if state.assistant_type == "cover_letter":
        emit_message(
            sid,
            "Anything else you'd like to work on? Reply `yes` to go back to questions, "
            "or `no` to wrap up.",
            key=f"export:followup:{len(state.export_results)}",
        )
        follow = interrupt({"kind": "post_export"})
        follow_text = (follow or "").strip().lower() if isinstance(follow, str) else ""
        if follow_text.startswith("y"):
            return {"phase": "qa_menu"}
    elif state.assistant_type == "interview_prep":
        emit_message(
            sid,
            "What's next? Reply `menu` to go back to the coach menu (mock interview, "
            "practice questions, tech deep-dive…), or anything else to wrap up.",
            key=f"export:followup:{len(state.export_results)}",
        )
        follow = interrupt({"kind": "post_export"})
        follow_text = (follow or "").strip().lower() if isinstance(follow, str) else ""
        if follow_text == "menu":
            return {"phase": "interview_menu"}

    emit_message(sid, "All done — good luck!")
    return {"phase": "done"}
