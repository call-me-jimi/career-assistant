"""Final export node: pick the artifacts, pick how to receive them, write them.

Each assistant offers a different set of artifacts and a different set of
delivery forms — a cover letter belongs in an application folder, an evaluation
report is usually something you just want to download. The per-assistant tables
below drive both the chat prompt and the quick-reply chips the UI renders.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from langgraph.types import interrupt

from backend.agent.interrupts import (
    action_finish,
    action_start,
    emit_export_ready,
    emit_message,
)
from backend.agent.state import ApplicationState, ExportResult
from backend.storage.journeys import get_journey, update_journey
from backend.storage.traces import list_traces
from backend.tools import exporters


@dataclass(frozen=True)
class ExportItem:
    key: str
    label: str
    available: Callable[[ApplicationState], bool]


_TRACES = ExportItem("traces", "LLM traces (json)", lambda s: True)

# What each assistant can hand over. Items whose `available` is False are hidden
# rather than offered and then failed.
EXPORT_ITEMS: dict[str, list[ExportItem]] = {
    "cover_letter": [
        ExportItem("cover_letter", "Cover letter (pdf)", lambda s: bool(s.cover_letter)),
        ExportItem("application", "Application info (md)", lambda s: True),
        ExportItem("job_ad", "Job ad (md)", lambda s: bool(s.job_description)),
        ExportItem("job_page", "Job page (png)", lambda s: bool(s.job_screenshot_path)),
        _TRACES,
    ],
    "interview_evaluator": [
        ExportItem("evaluation", "Interview evaluation (pdf)", lambda s: bool(s.interview_evaluation)),
        ExportItem("transcript", "Transcript (md)", lambda s: bool(s.interview_transcript)),
        _TRACES,
    ],
    "interview_prep": [
        ExportItem("briefing", "Interview briefing (pdf)", lambda s: bool(s.interview_briefing)),
        _TRACES,
    ],
    "career_advisor": [
        ExportItem("swot", "Career SWOT (pdf)", lambda s: bool(s.advisor_swot)),
        _TRACES,
    ],
}

# How each assistant can deliver. A single option is applied without asking.
# Career Advisor has no job journey, so it has no application folder to write
# into — download links are the only sensible form.
DELIVERY_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "cover_letter": [
        ("folder", "New application folder"),
        ("zip", "Zip download"),
    ],
    "interview_evaluator": [
        ("folder", "Application folder"),
        ("links", "Download links"),
        ("zip", "Zip download"),
    ],
    "interview_prep": [
        ("folder", "Application folder"),
        ("links", "Download links"),
    ],
    "career_advisor": [
        ("links", "Download links"),
    ],
}

# PDF content is chosen inside export_pdf by assistant_type, so every
# PDF-producing item routes to the same call.
_PDF_ITEMS = {"cover_letter", "evaluation", "briefing", "swot"}


def _next_phase(state: ApplicationState) -> str:
    """Cover Letter goes on to the tracker questions, whatever was exported.

    What the journey records — submitted or not, and any notes — is asked after
    the hand-over, so declining the files does not skip the tracker.
    """
    return "log_application" if state.assistant_type == "cover_letter" else "post_export"


def _temp_export_dir(session_id: str) -> Path:
    return (
        Path(tempfile.gettempdir())
        / "career_assistant_exports"
        / session_id
        / time.strftime("%Y.%m.%d")
    )


def _parse_selection(reply: object, items: list[ExportItem]) -> list[str]:
    """Accept either the UI's list of keys or a typed list of words."""
    keys = [i.key for i in items]
    if isinstance(reply, list):
        chosen = {str(r) for r in reply}
        return [k for k in keys if k in chosen]
    text = (reply or "").strip().lower() if isinstance(reply, str) else ""
    if not text or text == "none":
        return []
    if text == "all":
        return list(keys)
    words = {w.strip() for w in text.replace(",", " ").split() if w.strip()}
    return [k for k in keys if k in words]


async def _resolve_folder(state: ApplicationState) -> Path | None:
    """Where a `folder` delivery should write.

    None means "let the exporter create a fresh dated application folder".
    Cover Letter always starts a new one; the later assistants reuse whatever
    folder that job was exported to before, when there is one on the journey.
    """
    if state.assistant_type == "cover_letter" or not state.journey_id:
        return None
    journey = await get_journey(state.journey_id)
    stored = (journey or {}).get("export_folder") or ""
    if stored and Path(stored).is_dir():
        return Path(stored)
    return None


async def _remember_folder(state: ApplicationState, written: list[str]) -> None:
    """Persist the folder a job's artifacts landed in, for later sessions."""
    if not state.journey_id or not written:
        return
    try:
        await update_journey(state.journey_id, export_folder=str(Path(written[0]).parent))
    except Exception:
        pass  # never block an export over bookkeeping


async def _write_item(
    key: str, state_dict: dict, session_id: str, target: Path | None
) -> str:
    if key in _PDF_ITEMS:
        return await asyncio.to_thread(exporters.export_pdf, state_dict, target_dir=target)
    if key == "application":
        return await asyncio.to_thread(exporters.export_markdown, state_dict, target_dir=target)
    if key == "transcript":
        return await asyncio.to_thread(exporters.export_transcript, state_dict, target_dir=target)
    if key == "job_ad":
        return await asyncio.to_thread(exporters.export_job_ad, state_dict, target_dir=target)
    if key == "job_page":
        return await asyncio.to_thread(exporters.export_job_page, state_dict, target_dir=target)
    if key == "traces":
        traces = await list_traces(session_id)
        return await asyncio.to_thread(
            exporters.export_json, state_dict, traces, target_dir=target
        )
    raise RuntimeError(f"unknown export item: {key}")


async def export_node(state: ApplicationState) -> dict:
    sid = state.session_id
    done = len(state.export_results)
    items = [i for i in EXPORT_ITEMS.get(state.assistant_type, []) if i.available(state)]
    if not items:
        emit_message(sid, "There's nothing to export from this session yet.")
        return {"phase": _next_phase(state)}

    # 1. Which artifacts?
    listed = "\n".join(f"- `{i.key}` — {i.label}" for i in items)
    emit_message(
        sid,
        f"What would you like to take away?\n\n{listed}\n\n"
        "Pick any combination (or `all`), or say `none` to skip.",
        key=f"export:items:{done}",
    )
    reply = interrupt(
        {
            "kind": "export_items",
            "items": [{"value": i.key, "label": i.label} for i in items],
        }
    )
    selected = _parse_selection(reply, items)
    if not selected:
        emit_message(sid, "Skipped export — you can always come back to this.")
        return {"phase": _next_phase(state)}

    # 2. In what form?
    options = DELIVERY_OPTIONS.get(state.assistant_type) or [("links", "Download links")]
    if len(options) == 1:
        delivery = options[0][0]
    else:
        choices = "\n".join(f"- `{k}` — {label}" for k, label in options)
        emit_message(
            sid,
            f"How should I hand them over?\n\n{choices}",
            key=f"export:delivery:{done}",
        )
        delivery_reply = interrupt(
            {
                "kind": "export_delivery",
                "options": [{"value": k, "label": label} for k, label in options],
            }
        )
        picked = (
            (delivery_reply or "").strip().lower()
            if isinstance(delivery_reply, str)
            else ""
        )
        valid = {k for k, _ in options}
        if picked in valid:
            delivery = picked
        else:
            delivery = options[0][0]
            emit_message(
                sid,
                f"Defaulting to **{options[0][1]}**.",
                key=f"export:delivery-default:{done}",
            )

    target = await _resolve_folder(state) if delivery == "folder" else _temp_export_dir(sid)

    # 3. Write them.
    state_dict = state.model_dump(mode="json")
    results: list[ExportResult] = list(state.export_results)
    written: list[str] = []
    labels = {i.key: i.label for i in items}
    for key in selected:
        aid = action_start(sid, f"export_{key}", f"Exporting {labels[key]}")
        try:
            path = await _write_item(key, state_dict, sid, target)
        except Exception as exc:
            action_finish(sid, aid, status="error")
            emit_message(sid, f"✗ {labels[key]} failed: {exc}")
            continue
        action_finish(sid, aid)
        results.append(ExportResult(kind=key, path=path))
        written.append(path)
        if delivery == "links":
            emit_export_ready(sid, key, path)
            emit_message(sid, f"✓ {labels[key]} ready to download — `{Path(path).name}`")
        elif delivery == "folder":
            emit_message(sid, f"✓ {labels[key]} → `{path}`")

    # 4. Bundle, if that's the form they asked for.
    if delivery == "zip" and written:
        aid = action_start(sid, "export_zip", "Building the zip")
        try:
            archive = await asyncio.to_thread(
                exporters.export_zip, state_dict, written, _temp_export_dir(sid)
            )
            action_finish(sid, aid)
            results.append(ExportResult(kind="zip", path=archive))
            emit_export_ready(sid, "zip", archive)
            emit_message(sid, f"✓ {len(written)} file(s) zipped and ready to download.")
        except Exception as exc:
            action_finish(sid, aid, status="error")
            emit_message(sid, f"✗ zip failed: {exc}")

    if delivery == "folder":
        await _remember_folder(state, written)

    # Nothing may interrupt below this point: the writes above have already
    # happened, and LangGraph replays the node body from the top on resume.
    return {
        "export_results": results,
        "phase": _next_phase(state),
        "export_delivery": delivery,
    }


async def export_sheets_node(state: ApplicationState) -> dict:
    """Cover Letter only: log the application to the tracking spreadsheet.

    Its own node rather than a tail on `export_node`, because an interrupt
    placed after the file writes makes the resume pass write every artifact a
    second time.
    """
    sid = state.session_id
    emit_message(
        sid,
        "Want me to add a row for this application to your Google Sheet? "
        "Reply `yes` or `no`.",
        key=f"export:sheets:{len(state.export_results)}",
    )
    reply = interrupt({"kind": "export_sheets"})
    wants = (
        (reply or "").strip().lower().startswith("y") if isinstance(reply, str) else False
    )
    if not wants:
        return {"phase": "post_export"}

    aid = action_start(sid, "export_sheets", "Appending to Google Sheets")
    try:
        url = await asyncio.to_thread(
            exporters.export_google_sheets, state.model_dump(mode="json")
        )
    except Exception as exc:
        action_finish(sid, aid, status="error")
        emit_message(sid, f"✗ Google Sheets append failed: {exc}")
        return {"phase": "post_export"}
    action_finish(sid, aid)
    emit_message(sid, f"✓ added to your sheet → {url}")

    return {
        "export_results": list(state.export_results) + [ExportResult(kind="sheets", path=url)],
        "phase": "post_export",
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
