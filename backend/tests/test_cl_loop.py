"""Verify the cover-letter loop terminates on quality OR iteration cap."""

from __future__ import annotations

import pytest

from backend.agent.nodes import cl_loop as cl_loop_mod
from backend.agent.state import ApplicationState
from backend.llm.service import LLMCallResult


class FakeSettings:
    max_hm_iterations = 3
    quality_threshold = 8.5


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    monkeypatch.setattr(cl_loop_mod, "load_settings", lambda: FakeSettings())


@pytest.fixture
def base_state():
    return ApplicationState(
        session_id="test-session",
        applicant_name="Jane",
        cv_text="CV",
        candidate_profile="profile",
        job_title="Head of Data",
        company_name="Acme",
        job_description="JD",
        company_description="CD",
        job_source_type="direct",
        alignment_strategy="align",
    )


def _fake_hm_json(score: float) -> str:
    return (
        '{"overall_score": %.1f, "decision": "MAYBE", "first_impression": "", '
        '"strengths": [], "weaknesses": [], "suggestions": [], "reasoning": ""}'
    ) % score


@pytest.mark.asyncio
async def test_loop_stops_early_on_high_score(monkeypatch, base_state):
    calls = {"gen": 0, "hm": 0}

    async def fake_call_llm(*, task, system, user, session_id, history=None):
        if task == "cover_letter_generation":
            calls["gen"] += 1
            return LLMCallResult(text=f"draft-{calls['gen']}", model="m", provider="p")
        if task == "simulate_hiring_manager":
            calls["hm"] += 1
            return LLMCallResult(text=_fake_hm_json(9.2), model="m", provider="p")
        raise AssertionError(f"unexpected task {task}")

    monkeypatch.setattr(cl_loop_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(cl_loop_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(cl_loop_mod, "render_user_prompt", lambda stem, **kw: "usr")

    update = await cl_loop_mod.cl_loop_node(base_state)

    assert calls["gen"] == 1
    assert calls["hm"] == 1
    assert update["cover_letter"] == "draft-1"
    assert update["hm_iterations"] == 1
    assert len(update["cover_letter_versions"]) == 1


@pytest.mark.asyncio
async def test_loop_runs_max_iters_when_quality_low(monkeypatch, base_state):
    calls = {"gen": 0, "hm": 0}
    scores = [6.0, 6.5, 7.0]

    async def fake_call_llm(*, task, system, user, session_id, history=None):
        if task == "cover_letter_generation":
            calls["gen"] += 1
            return LLMCallResult(text=f"draft-{calls['gen']}", model="m", provider="p")
        if task == "simulate_hiring_manager":
            calls["hm"] += 1
            return LLMCallResult(
                text=_fake_hm_json(scores[calls["hm"] - 1]), model="m", provider="p"
            )
        raise AssertionError(f"unexpected task {task}")

    monkeypatch.setattr(cl_loop_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(cl_loop_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(cl_loop_mod, "render_user_prompt", lambda stem, **kw: "usr")

    update = await cl_loop_mod.cl_loop_node(base_state)

    assert calls["gen"] == 3
    assert calls["hm"] == 3
    # Best of {6.0, 6.5, 7.0} is iteration 3 (draft-3).
    assert update["cover_letter"] == "draft-3"
    assert update["hm_iterations"] == 3
