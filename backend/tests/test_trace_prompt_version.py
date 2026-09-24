"""Traces record which prompt template versions produced each call."""

from uuid import uuid4

import aiosqlite
from langchain_core.outputs import Generation, LLMResult

from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.observability.callbacks import event_bus_callback


def test_rendered_prompts_carry_their_template_name():
    user = render_user_prompt("detect_language", text="Hallo")
    system = load_system_prompt("simulate_hiring_manager")
    assert user.template == "detect_language.v1"
    assert system.template == "simulate_hiring_manager.system.v2"
    # Still plain text as far as every caller is concerned.
    assert isinstance(user, str) and "Hallo" in user


async def test_trace_row_stores_prompt_versions(test_db):
    run_id = uuid4()
    await event_bus_callback.on_llm_start(
        {},
        ["prompt"],
        run_id=run_id,
        metadata={
            "session_id": "s1",
            "task": "detect_language",
            "provider": "anthropic",
            "model": "m",
            "prompt_version": "detect_language.v1",
            "system_prompt_version": "detect_language.system.v1",
        },
    )
    await event_bus_callback.on_llm_end(
        LLMResult(generations=[[Generation(text="German")]]), run_id=run_id
    )
    async with aiosqlite.connect(test_db) as db:
        cur = await db.execute("SELECT prompt_version, system_prompt_version FROM traces")
        assert await cur.fetchall() == [("detect_language.v1", "detect_language.system.v1")]


async def test_call_llm_records_template_versions(test_db, monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from backend.config import LLMConfig
    from backend.llm import service

    cfg = LLMConfig(provider="ollama", model_name="fake")
    monkeypatch.setattr(
        service, "build_chat_model", lambda task, llm=None: (FakeListChatModel(responses=["German"]), cfg)
    )
    await service.call_llm(
        task="detect_language",
        system=load_system_prompt("detect_language"),
        user=render_user_prompt("detect_language", text="Hallo"),
        session_id="s1",
    )
    await service.call_llm(task="qa", system=None, user="inline, no template", session_id="s1")
    async with aiosqlite.connect(test_db) as db:
        cur = await db.execute(
            "SELECT prompt_version, system_prompt_version FROM traces ORDER BY trace_id"
        )
        assert await cur.fetchall() == [
            ("detect_language.v1", "detect_language.system.v1"),
            (None, None),
        ]
