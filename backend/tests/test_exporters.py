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
