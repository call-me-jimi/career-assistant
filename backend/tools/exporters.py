"""Export the final session artifacts: PDF, markdown, JSON, Google Sheets."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import zipfile
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


# Honorifics stripped from the front of a name when building the CV/PDF filename.
_HONORIFICS = {"dr", "prof", "mr", "mrs", "ms", "miss", "sir", "dame", "dipl", "ing", "mag", "phd", "md"}


def _applicant_slug(name: str) -> str:
    """Turn "Dr. Hendrik Hache" into "HendrikHache" for the PDF filename.

    Drops leading honorifics and any non-alphanumeric characters, then joins the
    remaining name parts. Returns "" when nothing usable is left.
    """
    tokens = (name or "").split()
    while tokens and tokens[0].rstrip(".").lower() in _HONORIFICS:
        tokens.pop(0)
    return "".join(re.sub(r"[^0-9A-Za-z]", "", tok) for tok in tokens)


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
    insights = evaluation.get("interviewer_insights") or []

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
    if insights:
        parts.append("")
        parts.append("### What the interviewer told you")
        parts.append("")
        for item in insights:
            topic = item.get("topic", "") or ""
            detail = item.get("detail", "") or ""
            parts.append(f"- **{topic}:** {detail}" if topic else f"- {detail}")
    return "\n".join(parts)


def _transcript_lines(segments: list[Any]) -> list[str]:
    """Render transcript segments as `[mm:ss] text` markdown lines.

    Speaker labels (when diarization ran) are printed only when the speaker
    changes, which keeps a human-readable transcript from turning into a wall
    of repeated names.
    """
    lines = []
    previous = None
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start") or 0.0)
        mm, ss = divmod(int(start), 60)
        speaker = (seg.get("speaker") or "").strip()
        if speaker and speaker != previous:
            prefix = f"**{speaker}** "
        elif speaker:
            prefix = "  "
        else:
            prefix = ""
        previous = speaker or previous
        lines.append(f"`[{mm:02d}:{ss:02d}]` {prefix}{text}")
    return lines


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
        transcript_lines = _transcript_lines(state.get("interview_transcript") or [])
        if transcript_lines:
            lines += ["## Interview transcript", ""] + transcript_lines + [""]

    path.write_text("\n".join(lines))
    log.info("wrote markdown %s", path)
    return str(path)


def export_transcript(state: dict[str, Any], target_dir: Path | None = None) -> str:
    """Write the interview recording's transcript as a standalone markdown file."""
    folder = _ensure_folder(state, target_dir)
    path = folder / "interview_transcript.md"
    header = [
        f"# Interview transcript — {state.get('company_name') or ''}".rstrip(" —"),
        "",
    ]
    if state.get("job_title"):
        header.append(f"**Job title:** {state.get('job_title')}")
    if state.get("interview_recording_filename"):
        header.append(f"**Recording:** {state.get('interview_recording_filename')}")
    duration = float(state.get("interview_recording_duration_sec") or 0.0)
    if duration:
        header.append(f"**Duration:** {duration / 60:.1f} min")
    if state.get("interview_transcript_language"):
        header.append(f"**Language:** {state.get('interview_transcript_language')}")
    header.append("")

    body = _transcript_lines(state.get("interview_transcript") or [])
    path.write_text("\n".join(header + (body or ["_(empty transcript)_"])) + "\n")
    log.info("wrote transcript %s", path)
    return str(path)


def export_json(
    state: dict[str, Any],
    traces: list[dict[str, Any]],
    target_dir: Path | None = None,
) -> str:
    folder = _ensure_folder(state, target_dir)
    path = folder / "llm_traces.json"
    payload = {"state": state, "llm_traces": traces}
    path.write_text(json.dumps(payload, indent=2, default=str))
    log.info("wrote traces %s", path)
    return str(path)


def export_job_page(state: dict[str, Any], target_dir: Path | None = None) -> str:
    """Copy the job-page screenshot, which outlives the posting going offline."""
    screenshot_name = state.get("job_screenshot_path") or ""
    src = SCREENSHOT_DIR / screenshot_name if screenshot_name else None
    if not src or not src.exists():
        raise RuntimeError("No job-page screenshot captured for this job.")
    dest = _ensure_folder(state, target_dir) / f"job_page{src.suffix or '.png'}"
    shutil.copyfile(src, dest)
    log.info("wrote job page %s", dest)
    return str(dest)


def export_job_ad(state: dict[str, Any], target_dir: Path | None = None) -> str:
    """Write the extracted job-ad text as its own markdown file."""
    job_ad = (state.get("job_description") or "").strip()
    if not job_ad:
        raise RuntimeError("No job ad text to export.")
    lines = [f"# Job ad — {state.get('job_title') or state.get('company_name') or ''}", ""]
    if state.get("company_name"):
        lines.append(f"**Company:** {state.get('company_name')}")
    if state.get("job_url"):
        lines.append(f"**URL:** {state.get('job_url')}")
    lines += ["", job_ad, ""]
    dest = _ensure_folder(state, target_dir) / "job_ad.md"
    dest.write_text("\n".join(lines))
    log.info("wrote job ad %s", dest)
    return str(dest)


def export_zip(state: dict[str, Any], paths: list[str], target_dir: Path) -> str:
    """Bundle already-written files into a single archive for download."""
    company = state.get("company_name") or state.get("applicant_name") or "Session"
    stem = _sanitize_filename(f"{company} - {time.strftime('%Y.%m.%d')}")
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / f"{stem}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            src = Path(p)
            if src.exists() and src != archive:
                zf.write(src, arcname=src.name)
    log.info("wrote zip %s", archive)
    return str(archive)


def export_pdf(state: dict[str, Any], target_dir: Path | None = None) -> str:
    import markdown as md
    from weasyprint import HTML

    folder = _ensure_folder(state, target_dir)

    assistant_type = state.get("assistant_type") or ""
    is_cover_letter = False

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
        slug = _applicant_slug(state.get("applicant_name") or "")
        filename = f"CoverLetter.{slug}.pdf" if slug else "CoverLetter.pdf"
        is_cover_letter = True
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
    # nl2br keeps single line breaks (e.g. the farewell and the signed name) as
    # separate lines in the cover letter instead of Markdown collapsing them.
    extensions = ["tables", "fenced_code"] + (["nl2br"] if is_cover_letter else [])
    body_html = md.markdown(body_text, extensions=extensions)
    if is_cover_letter:
        # Match a Google Doc with Calibri 11 (Carlito is the metric-compatible
        # clone): 1.15 line spacing and 1-inch margins keep a normal cover
        # letter on a single page.
        style = """
      @page { size: A4; margin: 2.54cm; }
      body { font-family: 'Carlito', 'Calibri', sans-serif; font-size: 11pt; line-height: 1.15; color: #222; }
      p { margin: 0 0 0.5em 0; }
      ul, ol { margin: 0 0 0.5em 1.5em; padding: 0; }
      li { margin-bottom: 0.15em; }
      strong { font-weight: bold; }
      em { font-style: italic; }
        """
    else:
        style = """
      body { font-family: 'Helvetica', sans-serif; font-size: 11pt; line-height: 1.6; color: #222; margin: 2cm; }
      h1 { font-size: 18pt; margin: 0 0 0.4em 0; color: #111; }
      h2 { font-size: 14pt; margin: 1.2em 0 0.3em 0; color: #111; border-bottom: 1px solid #ddd; padding-bottom: 0.15em; }
      h3 { font-size: 12pt; margin: 1em 0 0.2em 0; color: #333; }
      h4 { font-size: 11pt; margin: 1.2em 0 0.2em 0; color: #111; font-weight: bold; border-left: 3px solid #888; padding-left: 0.5em; }
      p { margin: 0 0 0.6em 0; }
      ul, ol { margin: 0 0 0.6em 1.5em; padding: 0; }
      li { margin-bottom: 0.25em; }
      strong { font-weight: bold; }
      em { font-style: italic; }
      code { font-family: monospace; background: #f4f4f4; padding: 0.1em 0.3em; border-radius: 3px; font-size: 10pt; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 0.8em; }
      th, td { border: 1px solid #ccc; padding: 0.4em 0.6em; text-align: left; }
      th { background: #f0f0f0; font-weight: bold; }
        """
    html = f"""
    <html><head><meta charset='utf-8'><style>{style}</style></head><body>
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
