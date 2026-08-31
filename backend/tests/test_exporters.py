"""Verify markdown and JSON exporters write files with expected content."""

from __future__ import annotations

import json
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


def test_export_json_includes_state_and_traces():
    traces = [{"task": "cover_letter_generation", "duration_ms": 1234}]
    path = Path(exporters.export_json(_state(), traces))
    payload = json.loads(path.read_text())
    assert payload["state"]["company_name"] == "Acme"
    assert payload["llm_traces"][0]["task"] == "cover_letter_generation"


def test_export_job_assets_copies_screenshot_and_ad(tmp_path, monkeypatch):
    monkeypatch.setattr(exporters, "SCREENSHOT_DIR", tmp_path / "shots")
    (tmp_path / "shots").mkdir()
    shot_src = exporters.SCREENSHOT_DIR / "acme_abc123.png"
    shot_src.write_bytes(b"\x89PNG fake")

    state = _state()
    state["job_screenshot_path"] = "acme_abc123.png"
    state["job_description"] = "We are hiring a Head of Data to lead…"

    written = exporters.export_job_assets(state)
    names = {Path(p).name for p in written}
    assert "job_page.png" in names
    assert "job_ad.md" in names

    ad = next(p for p in written if p.endswith("job_ad.md"))
    assert "Head of Data" in Path(ad).read_text()
    assert "We are hiring" in Path(ad).read_text()


def test_export_job_assets_skips_missing_screenshot():
    state = _state()
    state["job_screenshot_path"] = "does_not_exist.png"
    written = exporters.export_job_assets(state)
    assert not any(p.endswith(".png") for p in written)
