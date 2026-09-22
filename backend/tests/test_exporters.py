"""Verify markdown and JSON exporters write files with expected content."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import pytest

from backend.tools import exporters


@pytest.fixture(autouse=True)
def _tmp_export_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(exporters, "resolved_export_folder", lambda: tmp_path)
    return tmp_path


def _state():
    return {
        "applicant_name": "Jane Doe",
        "job_title": "Head of Data",
        "company_name": "Acme",
        "job_url": "https://example.com/job/1",
        "cover_letter": "Dear Hiring Team,\n\nI am excited…",
        "qa_items": [
            {"kind": "motivation", "question": "Why here?", "answer": "Because…"},
        ],
    }


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Dr. Hendrik Hache", "HendrikHache"),
        ("Hendrik Hache", "HendrikHache"),
        ("Prof. Dr. Jane Q. Doe", "JaneQDoe"),
        ("", ""),
        ("Dr.", ""),
    ],
)
def test_applicant_slug(name, expected):
    assert exporters._applicant_slug(name) == expected


def test_export_pdf_cover_letter_filename_includes_name():
    state = _state()
    state["cover_letter"] = "Dear Hiring Manager,\n\nBody.\n\nKind regards,\nDr. Hendrik Hache"
    state["applicant_name"] = "Dr. Hendrik Hache"
    path = Path(exporters.export_pdf(state))
    assert path.name == "CoverLetter.HendrikHache.pdf"
    assert path.exists()


def test_export_markdown_writes_expected_sections():
    path = Path(exporters.export_markdown(_state()))
    content = path.read_text()
    assert "Jane Doe" in content
    assert "Head of Data" in content
    assert "Cover letter" in content
    assert "Questions & Answers" in content
    assert "Why here?" in content


def test_export_transcript_writes_standalone_file():
    state = _state()
    state["interview_recording_filename"] = "round2.m4a"
    state["interview_recording_duration_sec"] = 1830.0
    state["interview_transcript_language"] = "en"
    state["interview_transcript"] = [
        {"start": 0.0, "text": "Thanks for joining."},
        {"start": 65.4, "text": "  "},  # blank segment is skipped
        {"start": 125.0, "text": "The team is six engineers."},
    ]
    path = Path(exporters.export_transcript(state))
    assert path.name == "interview_transcript.md"
    content = path.read_text()
    assert "round2.m4a" in content
    assert "30.5 min" in content
    assert "`[00:00]` Thanks for joining." in content
    assert "`[02:05]` The team is six engineers." in content
    assert "[01:05]" not in content


def _evaluator_state(interview_type="recruiter"):
    state = _state()
    state["assistant_type"] = "interview_evaluator"
    state["interview_type"] = interview_type
    state["interview_transcript"] = [{"start": 0.0, "text": "Thanks for joining."}]
    state["interview_evaluation"] = {"overall_score": 7.0, "summary": "Solid round."}
    return state


@pytest.mark.parametrize(
    "interview_type, expected",
    [
        ("recruiter", "recruiter_interview_transcript.md"),
        ("hiring_manager", "hiring_manager_interview_transcript.md"),
        ("", "interview_transcript.md"),  # unclassified round keeps the plain name
    ],
)
def test_evaluator_transcript_is_prefixed_with_the_round(interview_type, expected):
    path = Path(exporters.export_transcript(_evaluator_state(interview_type)))
    assert path.name == expected


def test_evaluator_traces_are_prefixed_but_the_zip_is_not(tmp_path):
    state = _evaluator_state("technical")
    assert Path(exporters.export_json(state, [])).name == "technical_llm_traces.json"

    src = tmp_path / "technical_interview_transcript.md"
    src.write_text("x")
    archive = Path(exporters.export_zip(state, [str(src)], tmp_path / "out"))
    assert archive.name.startswith("Acme - ")  # bundle stays company-dated


def test_evaluator_pdf_is_prefixed_with_the_round():
    path = Path(exporters.export_pdf(_evaluator_state("leadership")))
    assert path.name == "leadership_interview_evaluation.pdf"
    assert path.exists()


def test_prep_briefing_and_traces_are_prefixed_with_the_round():
    state = _state()
    state["assistant_type"] = "interview_prep"
    state["interview_type"] = "hiring_manager"
    state["interview_briefing"] = "## Snapshot\n\nLead with the platform story."
    path = Path(exporters.export_pdf(state))
    assert path.name == "hiring_manager_interview_briefing.pdf"
    assert path.exists()
    assert Path(exporters.export_json(state, [])).name == "hiring_manager_llm_traces.json"


def test_assistants_without_rounds_keep_unprefixed_names():
    """A cover letter or SWOT belongs to the job, not to an interview round."""
    state = _state()
    state["assistant_type"] = "cover_letter"
    state["interview_type"] = "technical"  # ignored outside the interview flows
    assert Path(exporters.export_json(state, [])).name == "llm_traces.json"
    assert Path(exporters.export_pdf(state)).name == "CoverLetter.JaneDoe.pdf"


def test_export_transcript_prints_speaker_only_on_change():
    state = _state()
    state["interview_transcript"] = [
        {"start": 0.0, "text": "Tell me about yourself.", "speaker": "SPEAKER_A"},
        {"start": 6.0, "text": "Sure, I lead data teams.", "speaker": "SPEAKER_B"},
        {"start": 12.0, "text": "For about fifteen years.", "speaker": "SPEAKER_B"},
        {"start": 18.0, "text": "Great.", "speaker": "SPEAKER_A"},
    ]
    body = Path(exporters.export_transcript(state)).read_text()
    assert body.count("**SPEAKER_B**") == 1  # not repeated on the follow-on line
    assert body.count("**SPEAKER_A**") == 2  # re-printed after the speaker changes
    assert "`[00:12]`   For about fifteen years." in body


def test_unique_path_walks_up_the_numbering(tmp_path):
    target = tmp_path / "interview_transcript.md"
    assert exporters._unique_path(target) == target

    target.write_text("first")
    second = exporters._unique_path(target)
    assert second.name == "interview_transcript (2).md"

    second.write_text("second")
    assert exporters._unique_path(target).name == "interview_transcript (3).md"


def test_re_export_never_overwrites_an_existing_file():
    state = _evaluator_state("technical")
    first = Path(exporters.export_transcript(state))
    first.write_text("hand-edited notes")

    state["interview_transcript"] = [{"start": 0.0, "text": "A later round."}]
    second = Path(exporters.export_transcript(state))

    assert second.name == "technical_interview_transcript (2).md"
    assert first.read_text() == "hand-edited notes"  # untouched
    assert "A later round." in second.read_text()


def test_re_export_never_overwrites_json_or_zip(tmp_path):
    state = _evaluator_state("panel")
    first = Path(exporters.export_json(state, []))
    assert Path(exporters.export_json(state, [])).name == "panel_llm_traces (2).json"
    assert first.exists()

    src = tmp_path / "artifact.md"
    src.write_text("x")
    out = tmp_path / "out"
    archive = Path(exporters.export_zip(state, [str(src)], out))
    again = Path(exporters.export_zip(state, [str(src)], out))
    assert archive.exists() and again.name.endswith(" (2).zip")


def test_export_json_includes_state_and_traces():
    traces = [{"task": "cover_letter_generation", "duration_ms": 1234}]
    path = Path(exporters.export_json(_state(), traces))
    payload = json.loads(path.read_text())
    assert payload["state"]["company_name"] == "Acme"
    assert payload["llm_traces"][0]["task"] == "cover_letter_generation"


def test_export_job_page_copies_the_screenshot(tmp_path, monkeypatch):
    monkeypatch.setattr(exporters, "SCREENSHOT_DIR", tmp_path / "shots")
    (tmp_path / "shots").mkdir()
    (exporters.SCREENSHOT_DIR / "acme_abc123.png").write_bytes(b"\x89PNG fake")

    state = _state()
    state["job_screenshot_path"] = "acme_abc123.png"
    path = Path(exporters.export_job_page(state))
    assert path.name == "job_page.png"
    assert path.read_bytes() == b"\x89PNG fake"


def test_export_job_page_raises_when_the_screenshot_is_gone():
    state = _state()
    state["job_screenshot_path"] = "does_not_exist.png"
    with pytest.raises(RuntimeError, match="screenshot"):
        exporters.export_job_page(state)


def test_export_job_ad_writes_title_and_body():
    state = _state()
    state["job_description"] = "We are hiring a Head of Data to lead…"
    path = Path(exporters.export_job_ad(state))
    assert path.name == "job_ad.md"
    body = path.read_text()
    assert "Head of Data" in body
    assert "We are hiring" in body


def test_export_job_ad_raises_without_job_text():
    with pytest.raises(RuntimeError, match="job ad"):
        exporters.export_job_ad(_state())


def test_export_zip_bundles_files_flat(tmp_path):
    a = tmp_path / "one.md"
    a.write_text("one")
    b = tmp_path / "nested" / "two.pdf"
    b.parent.mkdir()
    b.write_text("two")

    archive = Path(exporters.export_zip(_state(), [str(a), str(b)], tmp_path / "out"))
    assert archive.name == f"Acme - {time.strftime('%Y.%m.%d')}.zip"
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["one.md", "two.pdf"]


def test_export_zip_skips_paths_that_vanished(tmp_path):
    a = tmp_path / "one.md"
    a.write_text("one")
    archive = Path(
        exporters.export_zip(_state(), [str(a), str(tmp_path / "gone.pdf")], tmp_path / "out")
    )
    with zipfile.ZipFile(archive) as zf:
        assert zf.namelist() == ["one.md"]


# --- the spreadsheet row ----------------------------------------------------

HEADER = ["Title", "Company", "Location", "Status", "Submission", "Notes"]


def test_sheet_row_carries_the_notes_and_the_submission_date():
    applied_at = time.time()
    state = {**_state(), "application_notes": "EasyApply on LinkedIn.", "applied_at": applied_at}

    row, title_col = exporters._sheet_row(state, HEADER)

    assert title_col == 0
    assert row[HEADER.index("Notes")] == "EasyApply on LinkedIn."
    assert row[HEADER.index("Status")] == "Submitted"
    assert row[HEADER.index("Submission")] == time.strftime("%d/%m/%Y", time.localtime(applied_at))


def test_sheet_row_says_draft_until_the_application_is_submitted():
    """The row is appended while the letter is still in hand, so 'Submitted'
    has to come from the user's answer, not from the export happening."""
    row, _ = exporters._sheet_row({**_state(), "applied_at": None}, HEADER)

    assert row[HEADER.index("Status")] == "Draft"
    assert row[HEADER.index("Submission")] == ""
    assert row[HEADER.index("Notes")] == ""
