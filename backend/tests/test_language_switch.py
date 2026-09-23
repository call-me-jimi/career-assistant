"""extract_info must not interrupt after its LLM call; language_switch_node owns that."""
from __future__ import annotations

import pytest

from backend.agent.nodes import extract_info as ei_mod
from backend.agent.nodes import interview_context as ic_mod
from backend.agent.nodes import language_switch as ls_mod
from backend.agent.state import ApplicationState
from backend.llm.service import LLMCallResult


@pytest.mark.asyncio
async def test_extract_info_no_interrupt_when_text_is_long(monkeypatch):
    async def fake_call_llm(*, task, system, user, session_id, history=None):
        return LLMCallResult(
            text='{"job_title": "T", "company_name": "C", "job_description": "D", "job_language": "German"}',
            model="m", provider="p",
        )

    def exploding_interrupt(payload):
        raise AssertionError("extract_info must not interrupt after extraction")

    monkeypatch.setattr(ei_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(ei_mod, "interrupt", exploding_interrupt)
    monkeypatch.setattr(ei_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(ei_mod, "render_user_prompt", lambda stem, **kw: "usr")

    state = ApplicationState(session_id="s", language="English", job_raw_text="x" * 300)
    update = await ei_mod.extract_info_node(state)
    assert update["job_ad_language"] == "German"
    assert update["phase"] == "confirm_info"


@pytest.mark.asyncio
async def test_language_switch_yes_and_no(monkeypatch):
    state = ApplicationState(session_id="s", language="English", job_ad_language="German")

    monkeypatch.setattr(ls_mod, "interrupt", lambda payload: "yes")
    assert await ls_mod.language_switch_node(state) == {
        "language": "German",
        "language_offered": "German",
    }

    monkeypatch.setattr(ls_mod, "interrupt", lambda payload: "no")
    assert await ls_mod.language_switch_node(state) == {"language_offered": "German"}


@pytest.mark.asyncio
async def test_language_switch_skips_when_same_language(monkeypatch):
    def exploding_interrupt(payload):
        raise AssertionError("must not interrupt when languages match")

    monkeypatch.setattr(ls_mod, "interrupt", exploding_interrupt)
    state = ApplicationState(session_id="s", language="German", job_ad_language="german")
    assert await ls_mod.language_switch_node(state) == {}


@pytest.mark.asyncio
async def test_interview_language_switch_offers_and_switches(monkeypatch):
    state = ApplicationState(
        session_id="s", language="English", interview_context_language="German"
    )

    monkeypatch.setattr(ls_mod, "interrupt", lambda payload: "yes")
    assert await ls_mod.interview_language_switch_node(state) == {
        "language": "German",
        "language_offered": "German",
    }


@pytest.mark.asyncio
async def test_interview_language_switch_does_not_ask_twice(monkeypatch):
    """A German job ad already asked — the German HR mail must not ask again."""

    def exploding_interrupt(payload):
        raise AssertionError("must not ask again about a language already offered")

    monkeypatch.setattr(ls_mod, "interrupt", exploding_interrupt)
    state = ApplicationState(
        session_id="s",
        language="English",
        language_offered="German",
        interview_context_language="German",
    )
    assert await ls_mod.interview_language_switch_node(state) == {}


@pytest.mark.asyncio
async def test_interview_context_detects_language_after_the_interrupt(monkeypatch):
    calls: list[str] = []

    async def fake_call_llm(*, task, system, user, session_id, history=None):
        calls.append(task)
        return LLMCallResult(text="German\n", model="m", provider="p")

    monkeypatch.setattr(ic_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(ic_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(ic_mod, "render_user_prompt", lambda stem, **kw: "usr")
    monkeypatch.setattr(ic_mod, "interrupt", lambda payload: "Zweites Gespräch mit dem CTO")

    update = await ic_mod.interview_context_node(ApplicationState(session_id="s"))
    assert calls == ["detect_language"]
    assert update["interview_context_language"] == "German"
    assert update["phase"] == "interview_briefing"


@pytest.mark.asyncio
async def test_interview_context_none_skips_detection(monkeypatch):
    async def exploding_call_llm(**kwargs):
        raise AssertionError("nothing pasted — nothing to detect")

    monkeypatch.setattr(ic_mod, "call_llm", exploding_call_llm)
    monkeypatch.setattr(ic_mod, "interrupt", lambda payload: "none")

    update = await ic_mod.interview_context_node(ApplicationState(session_id="s"))
    assert update["interview_context"] == ""
    assert update["interview_context_language"] == ""


@pytest.mark.asyncio
async def test_interview_context_unknown_language_is_dropped(monkeypatch):
    async def fake_call_llm(*, task, system, user, session_id, history=None):
        return LLMCallResult(text="unknown", model="m", provider="p")

    monkeypatch.setattr(ic_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(ic_mod, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(ic_mod, "render_user_prompt", lambda stem, **kw: "usr")
    monkeypatch.setattr(ic_mod, "interrupt", lambda payload: "45 min, Zoom")

    update = await ic_mod.interview_context_node(ApplicationState(session_id="s"))
    assert update["interview_context_language"] == ""
