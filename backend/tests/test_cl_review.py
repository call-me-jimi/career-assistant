"""Tests for cl_review parsing helpers and revision-rescore behavior."""

from __future__ import annotations

import pytest

from backend.agent.nodes import cl_review as cl_review_mod
from backend.agent.nodes.cl_review import _parse_rescore_prefix


def test_rescore_prefix_with_colon():
    rescore, rest = _parse_rescore_prefix("rescore: more formal tone")
    assert rescore is True
    assert rest == "more formal tone"


def test_rescore_prefix_case_insensitive():
    rescore, rest = _parse_rescore_prefix("ReScore:  shorter")
    assert rescore is True
    assert rest == "shorter"


def test_rescore_prefix_with_space_separator():
    rescore, rest = _parse_rescore_prefix("rescore tone: more formal")
    assert rescore is True
    assert rest == "tone: more formal"


def test_rescore_prefix_absent():
    rescore, rest = _parse_rescore_prefix("tone: more formal")
    assert rescore is False
    assert rest == "tone: more formal"


def test_rescore_alone_returns_empty_remainder():
    rescore, rest = _parse_rescore_prefix("rescore")
    assert rescore is True
    assert rest == ""


def test_rescore_inside_word_is_not_a_prefix():
    rescore, rest = _parse_rescore_prefix("rescores are useful")
    assert rescore is False
    assert rest == "rescores are useful"


from backend.agent.state import ApplicationState, CoverLetterVersion
from backend.llm.service import LLMCallResult


def _fake_hm_json(score: float) -> str:
    return (
        '{"overall_score": %.1f, "decision": "MAYBE", "first_impression": "", '
        '"strengths": [], "weaknesses": [], "suggestions": [], "reasoning": ""}'
    ) % score


def _state_at_review() -> ApplicationState:
    v = CoverLetterVersion(
        version_id="v1", text="original letter", iteration=1, hm_score=7.0,
        hm_feedback={"overall_score": 7.0},
    )
    return ApplicationState(
        session_id="s1",
        applicant_name="Jane",
        cv_text="CV",
        job_description="JD",
        company_description="CD",
        cover_letter="original letter",
        cover_letter_versions=[v],
        best_version_id="v1",
        hm_iterations=1,
        phase="cl_review",
    )


@pytest.mark.asyncio
async def test_revision_with_rescore_attaches_hm_feedback(monkeypatch):
    state = _state_at_review()
    calls = {"refine": 0, "hm": 0}

    async def fake_call_llm(*, task, system, user, session_id, history=None):
        if task == "refine_cover_letter":
            calls["refine"] += 1
            return LLMCallResult(text="revised letter", model="m", provider="p")
        if task == "simulate_hiring_manager":
            calls["hm"] += 1
            return LLMCallResult(text=_fake_hm_json(8.4), model="m", provider="p")
        raise AssertionError(f"unexpected task {task}")

    monkeypatch.setattr(cl_review_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(cl_review_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(cl_review_mod, "render_user_prompt", lambda stem, **kw: "usr")
    monkeypatch.setattr(cl_review_mod, "interrupt", lambda payload: "rescore: more formal")
    monkeypatch.setattr(cl_review_mod, "emit_message", lambda *a, **kw: None)
    monkeypatch.setattr(cl_review_mod, "action_start", lambda *a, **kw: "aid")
    monkeypatch.setattr(cl_review_mod, "action_finish", lambda *a, **kw: None)

    update = await cl_review_mod.cl_review_node(state)

    assert calls["refine"] == 1
    assert calls["hm"] == 1
    versions = update["cover_letter_versions"]
    assert len(versions) == 2
    new_v = versions[-1]
    assert new_v.text == "revised letter"
    assert new_v.hm_score == 8.4
    assert new_v.hm_feedback is not None
    assert update["best_version_id"] == new_v.version_id


@pytest.mark.asyncio
async def test_revision_without_rescore_skips_hm(monkeypatch):
    state = _state_at_review()
    calls = {"refine": 0, "hm": 0}

    async def fake_call_llm(*, task, system, user, session_id, history=None):
        if task == "refine_cover_letter":
            calls["refine"] += 1
            return LLMCallResult(text="revised letter", model="m", provider="p")
        if task == "simulate_hiring_manager":
            calls["hm"] += 1
            return LLMCallResult(text=_fake_hm_json(8.4), model="m", provider="p")
        raise AssertionError(f"unexpected task {task}")

    monkeypatch.setattr(cl_review_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(cl_review_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(cl_review_mod, "render_user_prompt", lambda stem, **kw: "usr")
    monkeypatch.setattr(cl_review_mod, "interrupt", lambda payload: "tone: more formal")
    monkeypatch.setattr(cl_review_mod, "emit_message", lambda *a, **kw: None)
    monkeypatch.setattr(cl_review_mod, "action_start", lambda *a, **kw: "aid")
    monkeypatch.setattr(cl_review_mod, "action_finish", lambda *a, **kw: None)

    update = await cl_review_mod.cl_review_node(state)

    assert calls["refine"] == 1
    assert calls["hm"] == 0
    versions = update["cover_letter_versions"]
    assert versions[-1].hm_score is None
    assert versions[-1].hm_feedback is None
