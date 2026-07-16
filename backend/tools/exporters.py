"""Export the final session artifacts: PDF, markdown, JSON, Google Sheets."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from backend.config import resolved_export_folder
from backend.tools.screenshot import SCREENSHOT_DIR

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


def _render_evaluation_markdown(evaluation: dict[str, Any]) -> str:
    score = evaluation.get("overall_score", 0)
    decision = evaluation.get("decision", "?")
    summary = evaluation.get("summary", "") or ""
    strengths = evaluation.get("strengths") or []
    weaknesses = evaluation.get("weaknesses") or []
    improvements = evaluation.get("improvements") or []
    comm = evaluation.get("communication") or {}
    per_q = evaluation.get("per_question") or []

    def _bullets(items: list[str]) -> str:
        return "\n".join(f"- {x}" for x in items) if items else "_(none)_"

    parts = [
        f"**Decision:** {decision} · **Score:** {score}/10",
        "",
        summary,
        "",
        "### Strengths",
        _bullets(strengths),
        "",
        "### Weaknesses",
        _bullets(weaknesses),
        "",
        "### Points to improve",
        _bullets(improvements),
        "",
        "### Communication",
        f"- **Pace:** {comm.get('pace', '?')}",
        f"- **Filler words:** {', '.join(comm.get('filler_words') or []) or '(none observed)'}",
        f"- **Clarity:** {comm.get('clarity', '')}",
        f"- **Structure:** {comm.get('structure', '')}",
    ]
    if per_q:
        parts.append("")
        parts.append("### Per-question breakdown")
        for i, q in enumerate(per_q, 1):
            parts.append("")
            parts.append(f"#### Q{i}. {q.get('question', '')}")
            if q.get("answer_summary"):
                parts.append("")
                parts.append(f"**Answer:** {q['answer_summary']}")
            if q.get("strengths"):
                parts.append("")
                parts.append("**Strengths:**")
                parts.append("")
                for s in q["strengths"]:
                    parts.append(f"- {s}")
            if q.get("weaknesses"):
                parts.append("")
                parts.append("**Weaknesses:**")
                parts.append("")
                for w in q["weaknesses"]:
                    parts.append(f"- {w}")
            if q.get("suggested_improvement"):
                parts.append("")
                parts.append(f"**Improvement:** {q['suggested_improvement']}")
    return "\n".join(parts)


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

    evaluation = state.get("interview_evaluation")
    if evaluation:
        lines += [
            "## Interview evaluation",
            "",
            _render_evaluation_markdown(evaluation),
            "",
        ]
        transcript = state.get("interview_transcript") or []
        if transcript:
            lines += ["## Interview transcript", ""]
            for seg in transcript:
                start = float(seg.get("start") or 0.0) if isinstance(seg, dict) else 0.0
                text = (seg.get("text") if isinstance(seg, dict) else "") or ""
                if not text.strip():
                    continue
                mm, ss = divmod(int(start), 60)
                lines.append(f"`[{mm:02d}:{ss:02d}]` {text}")
            lines.append("")

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


def export_job_assets(state: dict[str, Any], target_dir: Path | None = None) -> list[str]:
    """Copy the source-of-truth job artifacts into the export folder.

    Captures the job-page screenshot (which survives the posting going offline)
    and the extracted job-ad text alongside the generated documents. Best-effort:
    a missing screenshot file or empty job text is skipped silently. Returns the
    list of written paths.
    """
    folder = _ensure_folder(state, target_dir)
    written: list[str] = []

    screenshot_name = state.get("job_screenshot_path") or ""
    if screenshot_name:
        src = SCREENSHOT_DIR / screenshot_name
        if src.exists():
            dest = folder / f"job_page{src.suffix or '.png'}"
            shutil.copyfile(src, dest)
            written.append(str(dest))
        else:
            log.warning("job screenshot %s not found, skipping", src)

    job_ad = (state.get("job_description") or "").strip()
    if job_ad:
        lines = [f"# Job ad — {state.get('job_title') or state.get('company_name') or ''}", ""]
        if state.get("company_name"):
            lines.append(f"**Company:** {state.get('company_name')}")
        if state.get("job_url"):
            lines.append(f"**URL:** {state.get('job_url')}")
        lines += ["", job_ad, ""]
        dest = folder / "job_ad.md"
        dest.write_text("\n".join(lines))
        written.append(str(dest))

    for path in written:
        log.info("wrote job asset %s", path)
    return written


def export_pdf(state: dict[str, Any], target_dir: Path | None = None) -> str:
    import markdown as md
    from weasyprint import HTML

    folder = _ensure_folder(state, target_dir)

    assistant_type = state.get("assistant_type") or ""

    if assistant_type == "interview_evaluator" and state.get("interview_evaluation"):
        body_text = (
            f"# Interview evaluation — {state.get('job_title') or state.get('company_name') or ''}\n\n"
            + _render_evaluation_markdown(state["interview_evaluation"])
        )
        title = f"Interview evaluation — {state.get('job_title') or state.get('company_name') or ''}"
        filename = "interview_evaluation.pdf"
    elif assistant_type == "interview_prep" and state.get("interview_briefing"):
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
    body_html = md.markdown(body_text, extensions=["tables", "fenced_code"])
    html = f"""
    <html><head><meta charset='utf-8'><style>
      body {{ font-family: 'Helvetica', sans-serif; font-size: 11pt; line-height: 1.6; color: #222; margin: 2cm; }}
      h1 {{ font-size: 18pt; margin: 0 0 0.4em 0; color: #111; }}
      h2 {{ font-size: 14pt; margin: 1.2em 0 0.3em 0; color: #111; border-bottom: 1px solid #ddd; padding-bottom: 0.15em; }}
      h3 {{ font-size: 12pt; margin: 1em 0 0.2em 0; color: #333; }}
      h4 {{ font-size: 11pt; margin: 1.2em 0 0.2em 0; color: #111; font-weight: bold; border-left: 3px solid #888; padding-left: 0.5em; }}
      p {{ margin: 0 0 0.6em 0; }}
      ul, ol {{ margin: 0 0 0.6em 1.5em; padding: 0; }}
      li {{ margin-bottom: 0.25em; }}
      strong {{ font-weight: bold; }}
      em {{ font-style: italic; }}
      code {{ font-family: monospace; background: #f4f4f4; padding: 0.1em 0.3em; border-radius: 3px; font-size: 10pt; }}
      table {{ border-collapse: collapse; width: 100%; margin-bottom: 0.8em; }}
      th, td {{ border: 1px solid #ccc; padding: 0.4em 0.6em; text-align: left; }}
      th {{ background: #f0f0f0; font-weight: bold; }}
    </style></head><body>
      {body_html}
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
