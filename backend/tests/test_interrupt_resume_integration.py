"""End-to-end interrupt/resume integration tests for the topology fixes.

Unlike the node-level unit tests (test_mock_interview_split.py,
test_language_switch.py), these drive the real node functions through
LangGraph's real interrupt/resume cycle with an in-memory checkpointer —
the same invariant SessionRunner relies on (a node body re-executes from the
top on resume). LLM and prompt loaders are stubbed so the runs are
deterministic. The mini-graphs mirror the wiring in graph_interview.py /
graph.py exactly.
"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from backend.agent.nodes import extract_info as ei
from backend.agent.nodes import interview_extras as ie
from backend.agent.nodes import language_switch as ls
from backend.agent.state import ApplicationState, ChatTurn
from backend.llm.service import LLMCallResult


def _extract_interrupt(snap):
    for t in (getattr(snap, "tasks", None) or ()):
        for it in (getattr(t, "interrupts", None) or ()):
            v = getattr(it, "value", None)
            if v is not None:
                return v
    return None


async def _drive(graph, config, first_input, replies):
    """Mirror SessionRunner: invoke, then resume through each interrupt.

    Returns (final state values, list of interrupt payloads seen).
    """
    reply_iter = iter(replies)
    seen: list = []
    await graph.ainvoke(first_input, config=config)
    while True:
        snap = await graph.aget_state(config)
        payload = _extract_interrupt(snap)
        if payload is None:
            return snap.values, seen
        seen.append(payload)
        try:
            reply = next(reply_iter)
        except StopIteration:
            return snap.values, seen
        await graph.ainvoke(Command(resume=reply), config=config)


@pytest.mark.asyncio
async def test_mock_interview_resume_loop_calls_llm_once_per_turn(monkeypatch):
    """Step 13: a full mock loop must call the LLM once per turn and never
    record a different question than the one the user was shown."""
    llm_calls: list[str] = []
    shown_questions: list[str] = []

    async def fake_llm(*, task, system, user, session_id, history=None):
        llm_calls.append(task)
        return LLMCallResult(text=f"TEXT::{task}::{len(llm_calls)}", model="m", provider="p")

    def rec_emit(sid, text, *a, **k):
        if text.startswith("**Q"):
            shown_questions.append(text.split(".** ", 1)[1])

    monkeypatch.setattr(ie, "call_llm", fake_llm)
    monkeypatch.setattr(ie, "emit_message", rec_emit)
    monkeypatch.setattr(ie, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(ie, "render_user_prompt", lambda stem, **kw: "usr")

    # mirrors graph_interview.py's mock-loop wiring
    def mock_answer_router(state: ApplicationState) -> str:
        return "interview_mock" if state.phase == "interview_mock" else "interview_menu"

    async def menu_stub(state: ApplicationState) -> dict:
        return {"phase": "menu_reached"}

    g = StateGraph(ApplicationState)
    g.add_node("interview_mock", ie.mock_interview_node)
    g.add_node("interview_mock_answer", ie.mock_interview_answer_node)
    g.add_node("interview_menu", menu_stub)
    g.add_edge(START, "interview_mock")
    g.add_edge("interview_mock", "interview_mock_answer")
    g.add_conditional_edges(
        "interview_mock_answer", mock_answer_router,
        {"interview_mock": "interview_mock", "interview_menu": "interview_menu"},
    )
    g.add_edge("interview_menu", END)
    graph = g.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "mock-1"}}
    state = ApplicationState(session_id="mock-1", job_title="SWE", company_name="ACME").model_dump()
    # Q1 -> answer -> feedback -> "next" -> Q2 -> "done" -> menu
    values, interrupts = await _drive(graph, config, state, ["my answer", "next", "done"])

    # LLM fires exactly once per generate turn (the resume-doubling bug is gone)
    assert llm_calls == ["mock_interview_question", "mock_interview_feedback", "mock_interview_question"]
    # every interrupt is owned by the answer node
    assert [iv.get("kind") for iv in interrupts] == ["mock_interview"] * 3
    # the questions stored in the transcript == the questions the user was shown
    transcript = [ChatTurn(**t) if isinstance(t, dict) else t for t in values["mock_interview_transcript"]]
    stored_qs = [t.content for t in transcript
                 if t.role == "assistant" and not t.content.startswith(ie._FEEDBACK_MARKER)]
    assert stored_qs and all(q in shown_questions for q in stored_qs)
    # exited cleanly across the topology
    assert values["phase"] == "menu_reached"


@pytest.mark.asyncio
async def test_language_switch_resume_runs_extraction_once(monkeypatch):
    """Step 12: extract_info must run once; the language_switch node owns the
    interrupt and applies (or skips) the switch on resume."""
    ei_calls: list[str] = []
    switch_keys: set[str] = set()

    async def fake_extract(*, task, system, user, session_id, history=None):
        ei_calls.append(task)
        return LLMCallResult(
            text='{"job_title":"Ingenieur","company_name":"ACME","job_description":"D","job_language":"German"}',
            model="m", provider="p",
        )

    def rec_emit(sid, text, *a, **k):
        # Model the EventBus key-dedup: the node re-runs on resume and re-emits,
        # but the real bus collapses emits sharing a stable key.
        if k.get("key") == "extract_info:language_switch":
            switch_keys.add(k["key"])

    monkeypatch.setattr(ei, "call_llm", fake_extract)
    monkeypatch.setattr(ei, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(ei, "render_user_prompt", lambda stem, **kw: "usr")
    monkeypatch.setattr(ls, "emit_message", rec_emit)

    async def fill_stub(state: ApplicationState) -> dict:
        return {"phase": "done"}

    def build():
        g = StateGraph(ApplicationState)
        g.add_node("extract_info", ei.extract_info_node)
        g.add_node("language_switch", ls.language_switch_node)
        g.add_node("fill_missing_info", fill_stub)
        g.add_edge(START, "extract_info")
        g.add_edge("extract_info", "language_switch")
        g.add_edge("language_switch", "fill_missing_info")
        g.add_edge("fill_missing_info", END)
        return g.compile(checkpointer=MemorySaver())

    long_text = "x" * 300  # skip extract_info's short-text interrupt

    # (A) German ad in an English session, user accepts -> switches; extraction ran once
    switch_keys.clear(); ei_calls.clear()
    vals, _ = await _drive(
        build(), {"configurable": {"thread_id": "ls-yes"}},
        ApplicationState(session_id="ls-yes", language="English", job_raw_text=long_text).model_dump(),
        ["yes"],
    )
    assert vals["job_ad_language"] == "German"
    assert vals["language"] == "German"
    assert ei_calls == ["extract_job_and_company_information"]  # once, not twice
    assert len(switch_keys) == 1  # one logical prompt despite the resume re-run

    # (B) user declines -> language unchanged
    switch_keys.clear(); ei_calls.clear()
    vals, _ = await _drive(
        build(), {"configurable": {"thread_id": "ls-no"}},
        ApplicationState(session_id="ls-no", language="English", job_raw_text=long_text).model_dump(),
        ["no"],
    )
    assert vals["language"] == "English"

    # (C) session already in the ad's language -> no interrupt, no prompt
    switch_keys.clear(); ei_calls.clear()
    vals, interrupts = await _drive(
        build(), {"configurable": {"thread_id": "ls-same"}},
        ApplicationState(session_id="ls-same", language="German", job_raw_text=long_text).model_dump(),
        [],
    )
    assert interrupts == []
    assert len(switch_keys) == 0
    assert vals["language"] == "German"
