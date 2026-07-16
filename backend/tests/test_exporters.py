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


def test_export_markdown_writes_expected_sections():
    path = Path(exporters.export_markdown(_state()))
    content = path.read_text()
    assert "Jane Doe" in content
    assert "Head of Data" in content
    assert "Cover letter" in content
    assert "Questions & Answers" in content
    assert "Why here?" in content


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
