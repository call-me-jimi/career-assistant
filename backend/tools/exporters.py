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


def _ensure_folder(state: dict[str, Any], target_dir: Path | None = None) -> Path:
    """Pick the destination folder.

    When `target_dir` is supplied (e.g. a per-session temp dir for download-only
    exports), use it as-is and skip the human-readable symlink. Otherwise fall
    back to the configured Applications folder with the company/date naming +
    symlink convention.
    """
    if target_dir is not None:
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

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


def export_markdown(state: dict[str, Any], target_dir: Path | None = None) -> str:
    folder = _ensure_folder(state, target_dir)
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

    transcript = state.get("mock_interview_transcript") or []
    if transcript:
        lines += ["## Mock interview transcript", ""]
        for turn in transcript:
            role = turn.get("role") if isinstance(turn, dict) else turn.role
            content = turn.get("content") if isinstance(turn, dict) else turn.content
            content = content or ""
            if content.startswith("<!-- fb -->"):
                label = "COACH"
                content = content[len("<!-- fb -->"):].lstrip()
            else:
                label = "INTERVIEWER" if role == "assistant" else "CANDIDATE"
            lines += [f"**{label}:** {content}", ""]

    extras = state.get("interview_extras") or []
    for item in extras:
        kind = item.get("kind", "")
        topic = item.get("topic", "")
        title = {
            "practice": "Practice — common questions",
            "tech": f"Tech deep-dive — {topic}",
            "questions": "Questions to ask the interviewer",
        }.get(kind, f"{kind} — {topic}")
        lines += [f"## {title}", "", item.get("content", ""), ""]

    if state.get("advisor_swot"):
        lines += ["## Career SWOT", "", state["advisor_swot"], ""]

    path.write_text("\n".join(lines))
    log.info("wrote markdown %s", path)
    return str(path)


def export_json(
    state: dict[str, Any],
    traces: list[dict[str, Any]],
    target_dir: Path | None = None,
) -> str:
    folder = _ensure_folder(state, target_dir)
    path = folder / "application.json"
    payload = {"state": state, "llm_traces": traces}
    path.write_text(json.dumps(payload, indent=2, default=str))
    log.info("wrote json %s", path)
    return str(path)


def export_pdf(state: dict[str, Any], target_dir: Path | None = None) -> str:
    from weasyprint import HTML

    folder = _ensure_folder(state, target_dir)

    assistant_type = state.get("assistant_type") or ""

    if assistant_type == "interview_prep" and state.get("interview_briefing"):
        body_text = state["interview_briefing"]
        title = f"Interview briefing — {state.get('job_title') or state.get('company_name') or ''}"
        filename = "interview_briefing.pdf"
    elif assistant_type == "career_advisor" and state.get("advisor_swot"):
        body_text = state["advisor_swot"]
        title = "Career SWOT"
        filename = "career_swot.pdf"
    elif state.get("cover_letter"):
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
    paragraphs = "".join(f"<p>{p.strip().replace(chr(10), '<br/>')}</p>" for p in body_text.split("\n\n") if p.strip())
    html = f"""
    <html><head><meta charset='utf-8'><style>
      body {{ font-family: 'Helvetica', sans-serif; font-size: 11pt; line-height: 1.4; color: #222; margin: 1.5cm; }}
      p {{ margin: 0 0 0.6em 0; }}
    </style></head><body>
      {paragraphs}
    </body></html>
    """
    HTML(string=html).write_pdf(str(path))
    log.info("wrote pdf %s", path)
    return str(path)


def export_google_sheets(state: dict[str, Any]) -> str:
    from backend.config import load_settings
    settings = load_settings()
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID") or settings.google_sheets_spreadsheet_id
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH")
    if not spreadsheet_id or not creds_path:
        raise RuntimeError("Google Sheets not configured (set env vars)")
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(spreadsheet_id).sheet1

    values = ws.get_all_values()
    header = values[0] if values else []

    def find_col(name: str) -> int | None:
        lname = name.strip().lower()
        for i, val in enumerate(header):
            if str(val).strip().lower() == lname:
                return i
        return None

    def col_letter(idx: int) -> str:
        result = ""
        idx += 1  # convert to 1-based
        while idx > 0:
            idx, rem = divmod(idx - 1, 26)
            result = chr(65 + rem) + result
        return result

    title_col = find_col("title") if find_col("title") is not None else 0
    company_col = find_col("company")
    location_col = find_col("location")
    status_col = find_col("status")
    submission_col = find_col("submission")
    notes_col = find_col("notes")

    job_title = (state.get("job_title") or "").replace('"', "'")
    job_url = (state.get("job_url") or "").strip()
    if job_title and job_url:
        title_cell = f'=HYPERLINK("{job_url}","{job_title}")'
    else:
        title_cell = job_title

    width = max(len(header), 1)
    row = [""] * width

    if 0 <= title_col < width:
        row[title_col] = title_cell
    if company_col is not None and 0 <= company_col < width:
        row[company_col] = state.get("company_name") or ""
    if location_col is not None and 0 <= location_col < width:
        row[location_col] = state.get("location") or ""
    if status_col is not None and 0 <= status_col < width:
        row[status_col] = "Submitted"
    if submission_col is not None and 0 <= submission_col < width:
        row[submission_col] = time.strftime("%d/%m/%Y")
    if notes_col is not None and 0 <= notes_col < width:
        row[notes_col] = ""

    # Find first empty row in Title column (skip header)
    target_row = None
    for idx, existing in enumerate(values, start=1):
        if idx == 1:
            continue
        title_val = existing[title_col].strip() if len(existing) > title_col else ""
        if title_val == "":
            target_row = idx
            break
    if target_row is None:
        target_row = len(values) + 1

    range_ref = f"A{target_row}:{col_letter(width - 1)}{target_row}"
    ws.update(range_ref, [row], value_input_option="USER_ENTERED")
    log.info("wrote google sheets row %d in %s", target_row, spreadsheet_id)
    return f"sheets:{spreadsheet_id}"
