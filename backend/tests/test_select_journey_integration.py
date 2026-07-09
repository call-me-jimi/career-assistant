"""Integration test (Step 5 of job journeys): drive the interview-prep graph's
cv_intake -> select_journey -> {collect_job | interview_context} wiring through
LangGraph's real interrupt/resume cycle, mirroring graph_interview.py exactly.

Pattern copied from test_interrupt_resume_integration.py.
"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from backend.agent.nodes import cv_intake as cv_intake_mod
from backend.agent.nodes.collect_job import collect_job_node
from backend.agent.nodes.cv_intake import cv_intake_node
from backend.agent.nodes.interview_context import interview_context_node
from backend.agent.nodes.select_journey import select_journey_node
from backend.agent.state import ApplicationState
from backend.storage.journeys import create_journey


def _extract_interrupt(snap):
    for t in (getattr(snap, "tasks", None) or ()):
        for it in (getattr(t, "interrupts", None) or ()):
            v = getattr(it, "value", None)
            if v is not None:
                return v
    return None


async def _drive(graph, config, first_input, replies):
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


async def _stub_research_company(state: ApplicationState) -> dict:
    return {"phase": "interview_context"}


def _build_mini_graph():
    """Mirrors graph_interview.py's cv_intake -> select_journey -> ... wiring."""
    g = StateGraph(ApplicationState)
    g.add_node("cv_intake", cv_intake_node)
    g.add_node("select_journey", select_journey_node)
    g.add_node("collect_job", collect_job_node)
    g.add_node("research_company", _stub_research_company)
    g.add_node("interview_context", interview_context_node)

    g.add_edge(START, "cv_intake")
    g.add_edge("cv_intake", "select_journey")

    def select_journey_router(state: ApplicationState) -> str:
        targets = {"select_journey", "collect_job", "research_company", "interview_context"}
        return state.phase if state.phase in targets else "collect_job"

    g.add_conditional_edges(
        "select_journey",
        select_journey_router,
        {t: t for t in ("select_journey", "collect_job", "research_company", "interview_context")},
    )
    g.add_edge("collect_job", END)
    g.add_edge("research_company", END)
    g.add_edge("interview_context", END)
    return g.compile(checkpointer=MemorySaver())


@pytest.mark.asyncio
async def test_continue_journey_skips_intake_to_interview_context(test_db, monkeypatch):
    async def fake_get_profile(profile_id):
        return {"cv_text": "CV text", "candidate_profile": "profile summary"}

    monkeypatch.setattr(cv_intake_mod, "get_profile", fake_get_profile)

    journey_id = await create_journey(
        profile_id="p1",
        job_url="https://example.com/job/1",
        job_title="Engineer",
        company_name="ACME",
        company_description="Makes widgets",
        cover_letter="Dear ACME, ...",
    )

    graph = _build_mini_graph()
    config = {"configurable": {"thread_id": "continue-1"}}
    state = ApplicationState(session_id="continue-1", assistant_type="interview_prep", profile_id="p1").model_dump()

    values, interrupts = await _drive(graph, config, state, ["1", "none"])

    kinds = [iv.get("kind") for iv in interrupts]
    assert "select_journey" in kinds
    assert kinds[-1] == "interview_context"
    assert values["journey_id"] == journey_id
    assert values["company_name"] == "ACME"
    assert values["cover_letter"] == "Dear ACME, ..."


@pytest.mark.asyncio
async def test_no_journeys_goes_straight_to_collect_job(test_db, monkeypatch):
    async def fake_get_profile(profile_id):
        return {"cv_text": "CV text", "candidate_profile": "profile summary"}

    monkeypatch.setattr(cv_intake_mod, "get_profile", fake_get_profile)

    graph = _build_mini_graph()
    config = {"configurable": {"thread_id": "no-journeys-1"}}
    state = ApplicationState(session_id="no-journeys-1", assistant_type="interview_prep", profile_id="p1").model_dump()

    values, interrupts = await _drive(graph, config, state, [])

    kinds = [iv.get("kind") for iv in interrupts]
    assert kinds == ["collect_job"]
