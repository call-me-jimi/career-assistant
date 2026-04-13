"""Export the final session artifacts: PDF, markdown, JSON, Google Sheets."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from backend.config import resolved_export_folder

log = logging.getLogger("assistant.exporters")


def _sanitize_filename(text: str) -> str:
    """Strip characters invalid for filesystem paths; preserve spaces."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", text)
    sanitized = sanitized.strip(". ")
    return sanitized[:200]


def _ensure_folder(state: dict[str, Any]) -> Path:
    base = resolved_export_folder()
    base.mkdir(parents=True, exist_ok=True)

    company = state.get("company_name") or state.get("applicant_name") or "Session"
    date_str = time.strftime("%Y.%m.%d")

    folder_name = _sanitize_filename(f"{company} - {date_str}")
    folder = base / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    # Create/update a symlink "<date> - <company>" → folder (relative target).
    try:
        link_name = _sanitize_filename(f"{date_str} - {company}")
        symlink_path = base / link_name
        if symlink_path.is_symlink() or symlink_path.exists():
            symlink_path.unlink()
        symlink_path.symlink_to(folder.name, target_is_directory=True)
    except Exception as exc:
        log.warning("failed to create export symlink: %s", exc)

    return folder


def export_markdown(state: dict[str, Any]) -> str:
    folder = _ensure_folder(state)
    path = folder / "application.md"
    lines = [
        f"# Session — {state.get('company_name') or state.get('applicant_name') or ''}",
        "",
        f"**Applicant:** {state.get('applicant_name') or ''}",
    ]
    if state.get("job_title"):
        lines.append(f"**Job title:** {state.get('job_title')}")
    if state.get("company_name"):
        lines.append(f"**Company:** {state.get('company_name')}")
    if state.get("job_url"):
        lines.append(f"**URL:** {state.get('job_url')}")
    lines.append("")

    if state.get("cover_letter"):
        lines += ["## Cover letter", "", state["cover_letter"], ""]

    qa = state.get("qa_items") or []
    if qa:
        lines.append("## Questions & Answers")
        lines.append("")
        for item in qa:
            lines.append(f"### {item.get('question', '')}")
            lines.append("")
            lines.append(item.get("answer", ""))
            lines.append("")

    if state.get("interview_briefing"):
        lines += ["## Interview briefing", "", state["interview_briefing"], ""]

    if state.get("advisor_swot"):
        lines += ["## Career SWOT", "", state["advisor_swot"], ""]

    path.write_text("\n".join(lines))
    log.info("wrote markdown %s", path)
    return str(path)


def export_json(state: dict[str, Any], traces: list[dict[str, Any]]) -> str:
    folder = _ensure_folder(state)
    path = folder / "application.json"
    payload = {"state": state, "llm_traces": traces}
    path.write_text(json.dumps(payload, indent=2, default=str))
    log.info("wrote json %s", path)
    return str(path)


def export_pdf(state: dict[str, Any]) -> str:
    from weasyprint import HTML

    folder = _ensure_folder(state)

    if state.get("cover_letter"):
        body_text = state["cover_letter"]
        title = state.get("job_title") or "Cover letter"
        filename = "cover_letter.pdf"
    elif state.get("interview_briefing"):
        body_text = state["interview_briefing"]
        title = f"Interview briefing — {state.get('job_title') or state.get('company_name') or ''}"
        filename = "interview_briefing.pdf"
    elif state.get("advisor_swot"):
        body_text = state["advisor_swot"]
        title = "Career SWOT"
        filename = "career_swot.pdf"
    else:
        raise RuntimeError("Nothing to export as PDF yet.")

    path = folder / filename
    body_html = body_text.replace("\n", "<br/>")
    html = f"""
    <html><head><meta charset='utf-8'><style>
      body {{ font-family: 'Helvetica', sans-serif; font-size: 11pt; line-height: 1.5; color: #222; margin: 2.5cm; }}
      h1 {{ font-size: 16pt; }}
      .meta {{ color: #666; font-size: 9pt; margin-bottom: 1.5em; }}
    </style></head><body>
      <h1>{title}</h1>
      <div class='meta'>{state.get('company_name') or ''} — {state.get('applicant_name') or ''}</div>
      <div>{body_html}</div>
    </body></html>
    """
    HTML(string=html).write_pdf(str(path))
    log.info("wrote pdf %s", path)
    return str(path)


def export_google_sheets(state: dict[str, Any]) -> str:
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH")
    if not spreadsheet_id or not creds_path:
        raise RuntimeError("Google Sheets not configured (set env vars)")
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.sheet1
    row = [
        time.strftime("%Y-%m-%d %H:%M:%S"),
        state.get("applicant_name") or "",
        state.get("company_name") or "",
        state.get("job_title") or "",
        state.get("job_url") or "",
        (state.get("cover_letter") or "")[:5000],
    ]
    ws.append_row(row, value_input_option="RAW")
    log.info("appended google sheets row to %s", spreadsheet_id)
    return f"sheets:{spreadsheet_id}"
