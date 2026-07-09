"""Tests for select_journey: the numbered job-journey picker."""

from __future__ import annotations

import pytest

from backend.agent.nodes import select_journey as sj
from backend.agent.state import ApplicationState

JOURNEY = {
    "journey_id": "j1",
    "profile_id": "p1",
    "job_url": "https://example.com/job/1",
    "job_title": "Engineer",
    "company_name": "ACME",
    "location": "Berlin",
    "job_description": "Build things",
    "company_description": "Makes widgets",
    "job_ad_language": "English",
    "job_source_type": "direct",
    "alignment_strategy": "",
    "inferred_role_context": "",
    "positioning_strategy": "",
    "cover_letter": "",
    "interview_briefing": "",
    "evaluation_summary": "",
    "created_at": 1000.0,
    "updated_at": 1000.0,
}


def _state(**kw) -> ApplicationState:
    return ApplicationState(session_id="s1", **kw)


# ---- select_journey_node ----------------------------------------------------


@pytest.mark.asyncio
async def test_node_silent_skip_when_no_journeys_and_no_query(monkeypatch):
    async def fake_list(profile_id, query="", limit=10):
        return []

    monkeypatch.setattr(sj, "list_journeys", fake_list)
    update = await sj.select_journey_node(_state())
    assert update == {"phase": "collect_job"}


@pytest.mark.asyncio
async def test_node_lists_and_interrupts(monkeypatch):
    messages = []

    async def fake_list(profile_id, query="", limit=10):
        return [JOURNEY]

    monkeypatch.setattr(sj, "list_journeys", fake_list)
    monkeypatch.setattr(sj, "emit_message", lambda sid, text, **kw: messages.append(text))
    monkeypatch.setattr(sj, "interrupt", lambda payload: "fresh")

    update = await sj.select_journey_node(_state())
    assert update == {"phase": "collect_job", "journey_query": ""}
    assert "ACME — Engineer" in messages[0]
    assert "no artifacts yet" in messages[0]


@pytest.mark.asyncio
async def test_node_no_matches_falls_back_to_full_list(monkeypatch):
    calls = []
    messages = []

    async def fake_list(profile_id, query="", limit=10):
        calls.append(query)
        if query:
            return []
        return [JOURNEY]

    monkeypatch.setattr(sj, "list_journeys", fake_list)
    monkeypatch.setattr(sj, "emit_message", lambda sid, text, **kw: messages.append(text))
    monkeypatch.setattr(sj, "interrupt", lambda payload: "fresh")

    update = await sj.select_journey_node(_state(journey_query="Nonexistent"))
    assert update == {"phase": "collect_job", "journey_query": ""}
    assert calls == ["Nonexistent", ""]
    assert "No matches for 'Nonexistent'" in messages[0]


@pytest.mark.asyncio
async def test_node_no_matches_and_no_journeys_at_all_falls_to_collect_job(monkeypatch):
    async def fake_list(profile_id, query="", limit=10):
        return []

    monkeypatch.setattr(sj, "list_journeys", fake_list)
    update = await sj.select_journey_node(_state(journey_query="Nonexistent"))
    assert update == {"phase": "collect_job", "journey_query": ""}


# ---- _handle_reply: continue by number --------------------------------------


@pytest.mark.asyncio
async def test_handle_reply_continue_seeds_nonempty_fields(monkeypatch):
    async def fake_get(journey_id):
        assert journey_id == "j1"
        return JOURNEY

    monkeypatch.setattr(sj, "get_journey", fake_get)
    monkeypatch.setattr(sj, "emit_message", lambda *a, **kw: None)

    update = await sj._handle_reply(_state(assistant_type="interview_prep"), [JOURNEY], "1")

    assert update["journey_id"] == "j1"
    assert update["journey_query"] == ""
    assert update["company_name"] == "ACME"
    assert update["job_description"] == "Build things"
    # empty fields on the journey are not seeded
    assert "cover_letter" not in update
    assert "alignment_strategy" not in update


@pytest.mark.asyncio
async def test_handle_reply_continue_out_of_range_is_not_a_number_match(monkeypatch):
    monkeypatch.setattr(sj, "emit_message", lambda *a, **kw: None)
    update = await sj._handle_reply(_state(), [JOURNEY], "5")
    # falls through to the short-text filter branch
    assert update == {"journey_query": "5", "phase": "select_journey"}


@pytest.mark.asyncio
async def test_handle_reply_continue_missing_journey_row_falls_back(monkeypatch):
    async def fake_get(journey_id):
        return None

    monkeypatch.setattr(sj, "get_journey", fake_get)
    update = await sj._handle_reply(_state(), [JOURNEY], "1")
    assert update == {"phase": "collect_job", "journey_query": ""}


# ---- _continue_phase per assistant type -------------------------------------


def test_continue_phase_interview_prep_missing_research():
    j = {**JOURNEY, "company_description": ""}
    assert sj._continue_phase("interview_prep", j) == "research_company"


def test_continue_phase_interview_prep_has_research():
    j = {**JOURNEY, "company_description": "Makes widgets"}
    assert sj._continue_phase("interview_prep", j) == "interview_context"


def test_continue_phase_interview_evaluator_always_evaluator_context():
    assert sj._continue_phase("interview_evaluator", JOURNEY) == "evaluator_context"


def test_continue_phase_cover_letter_missing_research():
    j = {**JOURNEY, "company_description": ""}
    assert sj._continue_phase("cover_letter", j) == "research_company"


def test_continue_phase_cover_letter_missing_source_type():
    j = {**JOURNEY, "company_description": "x", "job_source_type": ""}
    assert sj._continue_phase("cover_letter", j) == "classify_flow"


def test_continue_phase_cover_letter_missing_strategy():
    j = {**JOURNEY, "company_description": "x", "job_source_type": "direct",
         "positioning_strategy": "", "alignment_strategy": ""}
    assert sj._continue_phase("cover_letter", j) == "strategy"


def test_continue_phase_cover_letter_complete_goes_to_cl_loop():
    j = {**JOURNEY, "company_description": "x", "job_source_type": "direct",
         "positioning_strategy": "Lead with impact", "alignment_strategy": ""}
    assert sj._continue_phase("cover_letter", j) == "cl_loop"


# ---- _handle_reply: other branches ------------------------------------------


@pytest.mark.asyncio
async def test_handle_reply_fresh_keyword():
    update = await sj._handle_reply(_state(), [JOURNEY], "fresh")
    assert update == {"phase": "collect_job", "journey_query": ""}


@pytest.mark.asyncio
async def test_handle_reply_url_starts_fresh_with_stash():
    update = await sj._handle_reply(_state(), [JOURNEY], "https://jobs.example.com/42")
    assert update == {
        "job_url": "https://jobs.example.com/42",
        "phase": "collect_job",
        "journey_query": "",
    }


@pytest.mark.asyncio
async def test_handle_reply_bare_domain_treated_as_url():
    update = await sj._handle_reply(_state(), [JOURNEY], "acme.com/careers/42")
    assert update["job_url"] == "acme.com/careers/42"
    assert update["phase"] == "collect_job"


@pytest.mark.asyncio
async def test_handle_reply_short_text_is_a_query_filter():
    update = await sj._handle_reply(_state(), [JOURNEY], "Acme")
    assert update == {"journey_query": "Acme", "phase": "select_journey"}


@pytest.mark.asyncio
async def test_handle_reply_long_pasted_text_starts_fresh():
    long_text = ("We are looking for a Senior Engineer to join our team. " * 3).strip()
    update = await sj._handle_reply(_state(), [JOURNEY], long_text)
    assert update == {
        "job_raw_text": long_text,
        "phase": "collect_job",
        "journey_query": "",
    }
