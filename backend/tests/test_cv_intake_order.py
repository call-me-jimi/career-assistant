"""cv_intake must not run the LLM before its last interrupt (resume re-runs the node body)."""
from __future__ import annotations

import pytest

from backend.agent.nodes import cv_intake as mod
from backend.agent.state import ApplicationState
from backend.llm.service import LLMCallResult


@pytest.mark.asyncio
async def test_llm_runs_once_after_last_interrupt(monkeypatch):
    events: list[tuple[str, str]] = []
    replies = iter([{"cv_text": "MY CV"}, "My Label"])

    def fake_interrupt(payload):
        events.append(("interrupt", payload["kind"]))
        return next(replies)

    async def fake_call_llm(*, task, system, user, session_id, history=None):
        events.append(("llm", task))
        return LLMCallResult(text="PROFILE", model="m", provider="p")

    saved = {}

    async def fake_save_profile(**kw):
        saved.update(kw)
        return "pid-1"

    monkeypatch.setattr(mod, "interrupt", fake_interrupt)
    monkeypatch.setattr(mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(mod, "save_profile", fake_save_profile)
    monkeypatch.setattr(mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(mod, "render_user_prompt", lambda stem, **kw: "usr")

    state = ApplicationState(session_id="s", applicant_name="Jane")
    update = await mod.cv_intake_node(state)

    llm_indexes = [i for i, (k, _) in enumerate(events) if k == "llm"]
    interrupt_indexes = [i for i, (k, _) in enumerate(events) if k == "interrupt"]
    assert len(llm_indexes) == 1
    assert max(interrupt_indexes) < llm_indexes[0]  # LLM strictly after the last interrupt
    assert update["profile_id"] == "pid-1"
    assert saved["candidate_profile"] == "PROFILE"
    assert saved["name"] == "My Label"
