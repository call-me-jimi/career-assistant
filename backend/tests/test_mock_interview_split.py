"""Mock interview: generate node must never interrupt; answer node owns the interrupt."""
from __future__ import annotations

import pytest

from backend.agent.nodes import interview_extras as mod
from backend.agent.state import ApplicationState, ChatTurn
from backend.llm.service import LLMCallResult


def _exploding_interrupt(payload):
    raise AssertionError("generate node must not interrupt")


async def _fake_llm(*, task, system, user, session_id, history=None):
    return LLMCallResult(text=f"OUT-{task}", model="m", provider="p")


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(mod, "call_llm", _fake_llm)
    monkeypatch.setattr(mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(mod, "render_user_prompt", lambda stem, **kw: "usr")


@pytest.mark.asyncio
async def test_generate_question_no_interrupt(monkeypatch):
    monkeypatch.setattr(mod, "interrupt", _exploding_interrupt)
    state = ApplicationState(session_id="s", job_title="T", company_name="C")
    update = await mod.mock_interview_node(state)
    assert update["phase"] == "interview_mock_answer"
    assert update["mock_interview_transcript"][-1].role == "assistant"
    assert "OUT-mock_interview_question" in update["mock_interview_transcript"][-1].content


@pytest.mark.asyncio
async def test_generate_feedback_no_interrupt(monkeypatch):
    monkeypatch.setattr(mod, "interrupt", _exploding_interrupt)
    turns = [
        ChatTurn(role="assistant", content="Q1?"),
        ChatTurn(role="user", content="my answer"),
    ]
    state = ApplicationState(session_id="s", mock_interview_transcript=turns)
    update = await mod.mock_interview_node(state)
    assert update["phase"] == "interview_mock_answer"
    assert update["mock_interview_transcript"][-1].content.startswith(mod._FEEDBACK_MARKER)


@pytest.mark.asyncio
async def test_answer_node_done_and_answer(monkeypatch):
    state = ApplicationState(
        session_id="s",
        mock_interview_transcript=[ChatTurn(role="assistant", content="Q1?")],
    )
    monkeypatch.setattr(mod, "interrupt", lambda payload: "done")
    assert await mod.mock_interview_answer_node(state) == {"phase": "interview_menu"}

    monkeypatch.setattr(mod, "interrupt", lambda payload: "my answer")
    update = await mod.mock_interview_answer_node(state)
    assert update["phase"] == "interview_mock"
    assert update["mock_interview_transcript"][-1] == ChatTurn(role="user", content="my answer")
