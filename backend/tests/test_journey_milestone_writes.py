"""Tests for Step 6 of job journeys: milestone writes to job_journeys at each
node that produces persistable job/strategy/artifact data. Every write site is
wrapped in try/except so persistence failures never block the chat flow —
these tests assert the happy path actually persists.
"""

from __future__ import annotations

import json

import pytest

from backend.agent.nodes import confirm_info as confirm_info_mod
from backend.agent.nodes import evaluator as evaluator_mod
from backend.agent.nodes import interview_review as interview_review_mod
from backend.agent.nodes import research_company as research_company_mod
from backend.agent.nodes import strategy as strategy_mod
from backend.agent.nodes import synthesize_learning as synthesize_learning_mod
from backend.agent.state import ApplicationState
from backend.llm.service import LLMCallResult
from backend.storage.journeys import create_journey, get_journey


def _state(**kw) -> ApplicationState:
    return ApplicationState(session_id="s1", **kw)


# ---- 6a: confirm_info_node --------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_info_creates_journey_on_first_confirm(test_db, monkeypatch):
    monkeypatch.setattr(confirm_info_mod, "interrupt", lambda payload: "yes")
    monkeypatch.setattr(confirm_info_mod, "emit_message", lambda *a, **kw: None)

    state = _state(
        profile_id="p1",
        job_url="https://example.com/job/1",
        job_title="Engineer",
        company_name="ACME",
        location="Berlin",
        job_description="Build things",
        job_ad_language="English",
    )
    update = await confirm_info_mod.confirm_info_node(state)

    assert update["journey_id"]
    journey = await get_journey(update["journey_id"])
    assert journey["company_name"] == "ACME"
    assert journey["job_title"] == "Engineer"
    assert journey["location"] == "Berlin"


@pytest.mark.asyncio
async def test_confirm_info_correction_overlays_field(test_db, monkeypatch):
    monkeypatch.setattr(confirm_info_mod, "interrupt", lambda payload: "company: NewCo")
    monkeypatch.setattr(confirm_info_mod, "emit_message", lambda *a, **kw: None)

    state = _state(profile_id="p1", job_title="Engineer", company_name="ACME")
    update = await confirm_info_mod.confirm_info_node(state)

    assert update["company_name"] == "NewCo"
    journey = await get_journey(update["journey_id"])
    assert journey["company_name"] == "NewCo"


@pytest.mark.asyncio
async def test_confirm_info_updates_existing_journey_when_journey_id_set(test_db, monkeypatch):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    monkeypatch.setattr(confirm_info_mod, "interrupt", lambda payload: "location: Remote")
    monkeypatch.setattr(confirm_info_mod, "emit_message", lambda *a, **kw: None)

    state = _state(profile_id="p1", journey_id=jid, job_title="Engineer", company_name="ACME")
    update = await confirm_info_mod.confirm_info_node(state)

    assert update["journey_id"] == jid
    journey = await get_journey(jid)
    assert journey["location"] == "Remote"


# ---- 6b: research_company_node ----------------------------------------------


@pytest.mark.asyncio
async def test_research_company_updates_journey_description(test_db, monkeypatch):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")

    async def fake_llm(*, task, system, user, session_id):
        return LLMCallResult(text="ACME makes widgets.", model="m", provider="p")

    monkeypatch.setattr(research_company_mod, "tavily_search", lambda q, max_results=5: [{"title": "t", "content": "c"}])
    monkeypatch.setattr(research_company_mod, "call_llm", fake_llm)
    monkeypatch.setattr(research_company_mod, "emit_message", lambda *a, **kw: None)
    monkeypatch.setattr(research_company_mod, "action_start", lambda *a, **kw: "aid")
    monkeypatch.setattr(research_company_mod, "action_finish", lambda *a, **kw: None)

    state = _state(journey_id=jid, company_name="ACME", job_title="Engineer")
    update = await research_company_mod.research_company_node(state)

    assert "ACME makes widgets." in update["company_description"]
    journey = await get_journey(jid)
    assert journey["company_description"] == update["company_description"]


# ---- 6c: strategy_node -------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_direct_updates_journey(test_db, monkeypatch):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")

    async def fake_llm(*, task, system, user, session_id):
        return LLMCallResult(text="Align on X.", model="m", provider="p")

    monkeypatch.setattr(strategy_mod, "call_llm", fake_llm)
    monkeypatch.setattr(strategy_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(strategy_mod, "render_user_prompt", lambda stem, **kw: "usr")
    monkeypatch.setattr(strategy_mod, "emit_message", lambda *a, **kw: None)
    monkeypatch.setattr(strategy_mod, "action_start", lambda *a, **kw: "aid")
    monkeypatch.setattr(strategy_mod, "action_finish", lambda *a, **kw: None)

    state = _state(journey_id=jid, job_source_type="direct", candidate_profile="CV", job_description="JD")
    update = await strategy_mod.strategy_node(state)

    assert update["alignment_strategy"] == "Align on X."
    journey = await get_journey(jid)
    assert journey["alignment_strategy"] == "Align on X."
    assert journey["job_source_type"] == "direct"


@pytest.mark.asyncio
async def test_strategy_recruiter_updates_journey(test_db, monkeypatch):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    calls = {"n": 0}

    async def fake_llm(*, task, system, user, session_id):
        calls["n"] += 1
        text = "Inferred role." if task == "infer_role" else "Positioning."
        return LLMCallResult(text=text, model="m", provider="p")

    monkeypatch.setattr(strategy_mod, "call_llm", fake_llm)
    monkeypatch.setattr(strategy_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(strategy_mod, "render_user_prompt", lambda stem, **kw: "usr")
    monkeypatch.setattr(strategy_mod, "emit_message", lambda *a, **kw: None)
    monkeypatch.setattr(strategy_mod, "action_start", lambda *a, **kw: "aid")
    monkeypatch.setattr(strategy_mod, "action_finish", lambda *a, **kw: None)

    state = _state(journey_id=jid, job_source_type="recruiter", candidate_profile="CV", job_description="JD")
    update = await strategy_mod.strategy_node(state)

    assert update["positioning_strategy"] == "Positioning."
    journey = await get_journey(jid)
    assert journey["inferred_role_context"] == "Inferred role."
    assert journey["positioning_strategy"] == "Positioning."
    assert journey["job_source_type"] == "recruiter"


# ---- 6d: synthesize_learning_node --------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_learning_writes_cover_letter_even_when_learning_disabled(test_db, monkeypatch):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")

    # profile_id=None makes _should_run() False so the rest of the (LLM-heavy) body is skipped,
    # isolating the top-of-function journey write this step adds.
    state = _state(journey_id=jid, profile_id=None, cover_letter="Dear ACME, ...")
    update = await synthesize_learning_mod.synthesize_learning_node(state)

    assert update == {}
    journey = await get_journey(jid)
    assert journey["cover_letter"] == "Dear ACME, ..."


# ---- 6e: interview_review_node -----------------------------------------------


@pytest.mark.asyncio
async def test_interview_review_accept_writes_briefing(test_db, monkeypatch):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    monkeypatch.setattr(interview_review_mod, "interrupt", lambda payload: "accept")
    monkeypatch.setattr(interview_review_mod, "emit_message", lambda *a, **kw: None)

    state = _state(journey_id=jid, interview_briefing="Prep notes here.")
    update = await interview_review_mod.interview_review_node(state)

    assert update == {"phase": "interview_menu"}
    journey = await get_journey(jid)
    assert journey["interview_briefing"] == "Prep notes here."


# ---- 6f: evaluator_review_node ------------------------------------------------


@pytest.mark.asyncio
async def test_evaluator_review_accept_writes_evaluation_summary(test_db, monkeypatch):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    monkeypatch.setattr(evaluator_mod, "interrupt", lambda payload: "accept")
    monkeypatch.setattr(evaluator_mod, "emit_message", lambda *a, **kw: None)

    evaluation = {"overall_score": 7.5, "summary": "Solid performance."}
    # profile_id=None skips save_coaching_insight, isolating the journey write.
    state = _state(journey_id=jid, profile_id=None, interview_evaluation=evaluation)
    update = await evaluator_mod.evaluator_review_node(state)

    assert update == {"phase": "export"}
    journey = await get_journey(jid)
    stored = json.loads(journey["evaluation_summary"])
    assert stored == {"overall_score": 7.5, "summary": "Solid performance."}
