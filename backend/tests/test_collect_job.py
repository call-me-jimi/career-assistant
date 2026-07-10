"""Tests for collect_job's stash guard (Step 4 of job journeys): honor
job_url / job_raw_text pre-seeded by select_journey without re-prompting."""

from __future__ import annotations

import pytest

from backend.agent.nodes import collect_job as cj
from backend.agent.state import ApplicationState


def _patch_scrape_flow(monkeypatch, *, screenshot):
    """Patch collect_job's URL-scrape collaborators. ``screenshot`` is the value
    capture_screenshot resolves to (a filename, or None on failure)."""
    def boom(payload):
        raise AssertionError("interrupt() should not be called when job_url is pre-seeded")

    async def fake_capture(url, *, name_hint=""):
        return screenshot

    monkeypatch.setattr(cj, "interrupt", boom)
    monkeypatch.setattr(cj, "emit_message", lambda *a, **kw: None)
    monkeypatch.setattr(cj, "action_start", lambda *a, **kw: "aid")
    monkeypatch.setattr(cj, "action_finish", lambda *a, **kw: None)
    monkeypatch.setattr(cj, "scrape_job_page", lambda url: {"title": "Engineer | ACME Careers", "raw_text": "job body"})
    monkeypatch.setattr(cj, "capture_screenshot", fake_capture)


@pytest.mark.asyncio
async def test_stashed_url_skips_interrupt_and_scrapes(monkeypatch):
    _patch_scrape_flow(monkeypatch, screenshot="acme_deadbeef.png")

    state = ApplicationState(session_id="s1", job_url="https://example.com/job/1")
    update = await cj.collect_job_node(state)

    assert update["job_url"] == "https://example.com/job/1"
    assert update["job_raw_text"] == "job body"
    assert update["job_screenshot_path"] == "acme_deadbeef.png"
    assert update["phase"] == "extract_info"


@pytest.mark.asyncio
async def test_screenshot_failure_does_not_block_scrape(monkeypatch):
    """A failed capture (None) must leave an empty path and still advance."""
    _patch_scrape_flow(monkeypatch, screenshot=None)

    state = ApplicationState(session_id="s1", job_url="https://example.com/job/1")
    update = await cj.collect_job_node(state)

    assert update["job_screenshot_path"] == ""
    assert update["phase"] == "extract_info"


@pytest.mark.asyncio
async def test_stashed_pasted_text_skips_interrupt(monkeypatch):
    def boom(payload):
        raise AssertionError("interrupt() should not be called when job_raw_text is pre-seeded")

    monkeypatch.setattr(cj, "interrupt", boom)
    monkeypatch.setattr(cj, "emit_message", lambda *a, **kw: None)

    state = ApplicationState(session_id="s1", job_raw_text="We need a Senior Engineer...")
    update = await cj.collect_job_node(state)

    assert update == {
        "job_url": "",
        "job_raw_text": "We need a Senior Engineer...",
        "phase": "extract_info",
    }


@pytest.mark.asyncio
async def test_no_stash_falls_back_to_interrupt(monkeypatch):
    monkeypatch.setattr(cj, "interrupt", lambda payload: {"url": "", "text": "pasted via prompt"})
    monkeypatch.setattr(cj, "emit_message", lambda *a, **kw: None)

    state = ApplicationState(session_id="s1")
    update = await cj.collect_job_node(state)

    assert update == {
        "job_url": "",
        "job_raw_text": "pasted via prompt",
        "phase": "extract_info",
    }
