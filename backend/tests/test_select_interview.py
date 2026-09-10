"""Tests for select_interview: the per-round picker shared by prep and evaluator."""

from __future__ import annotations

import pytest

from backend.agent.nodes import select_interview as si
from backend.agent.state import ApplicationState

ROUND = {
    "interview_id": "i1",
    "journey_id": "j1",
    "profile_id": "p1",
    "interview_type": "technical",
    "label": "pair session",
    "context": "90 min with the lead dev",
    "briefing": "Prep notes: lead with the platform story",
    "evaluation_summary": "",
    "briefing_at": 1000.0,
    "evaluation_at": None,
    "created_at": 900.0,
    "updated_at": 1000.0,
}


def _state(**kw) -> ApplicationState:
    kw.setdefault("journey_id", "j1")
    return ApplicationState(session_id="s1", **kw)


def _patch(monkeypatch, reply, rounds=(), created="new-id"):
    messages: list[str] = []
    created_calls: list[dict] = []
    updated_calls: list[tuple] = []

    async def fake_list(journey_id):
        return list(rounds)

    async def fake_create(**kwargs):
        created_calls.append(kwargs)
        return created

    async def fake_update(interview_id, **fields):
        updated_calls.append((interview_id, fields))

    monkeypatch.setattr(si, "list_interviews", fake_list)
    monkeypatch.setattr(si, "create_interview", fake_create)
    monkeypatch.setattr(si, "update_interview", fake_update)
    monkeypatch.setattr(si, "emit_message", lambda sid, text, **kw: messages.append(text))
    monkeypatch.setattr(si, "interrupt", lambda payload: reply)
    return messages, created_calls, updated_calls


@pytest.mark.asyncio
async def test_new_round_created_from_type_name(monkeypatch):
    messages, created, _ = _patch(monkeypatch, reply="hiring manager")

    update = await si.select_interview_node(
        _state(assistant_type="interview_prep", interview_context="Meet the manager")
    )

    assert update["interview_type"] == "hiring_manager"
    assert update["interview_id"] == "new-id"
    assert update["phase"] == "interview_briefing"
    assert created[0]["context"] == "Meet the manager"
    assert "Hiring manager" in messages[-1]


@pytest.mark.asyncio
async def test_type_with_label(monkeypatch):
    _, created, _ = _patch(monkeypatch, reply="technical: pair with the lead dev")

    update = await si.select_interview_node(_state(assistant_type="interview_prep"))

    assert update["interview_type"] == "technical"
    assert update["interview_label"] == "pair with the lead dev"
    assert created[0]["label"] == "pair with the lead dev"


@pytest.mark.asyncio
async def test_existing_round_seeds_its_briefing(monkeypatch):
    messages, _, _ = _patch(monkeypatch, reply="1", rounds=[ROUND])

    update = await si.select_interview_node(_state(assistant_type="interview_evaluator"))

    assert update["interview_id"] == "i1"
    assert update["interview_briefing"] == ROUND["briefing"]
    assert update["interview_context"] == ROUND["context"]
    assert update["phase"] == "evaluator_context"
    assert "Technical — pair session" in messages[0]
    assert "briefing ✓" in messages[0]


@pytest.mark.asyncio
async def test_evaluator_new_round_drops_briefing_from_another_round(monkeypatch):
    _patch(monkeypatch, reply="screening", rounds=[ROUND])

    update = await si.select_interview_node(
        _state(
            assistant_type="interview_evaluator",
            interview_briefing="Briefing written for the technical round",
        )
    )

    assert update["interview_type"] == "screening"
    assert update["interview_briefing"] == ""


@pytest.mark.asyncio
async def test_prep_new_round_keeps_previous_briefing_for_carry_over(monkeypatch):
    _patch(monkeypatch, reply="screening", rounds=[ROUND])

    update = await si.select_interview_node(
        _state(assistant_type="interview_prep", interview_briefing="Round 1 prep")
    )

    assert "interview_briefing" not in update


@pytest.mark.asyncio
async def test_unrecognised_reply_loops(monkeypatch):
    messages, created, _ = _patch(monkeypatch, reply="uhh no idea")

    update = await si.select_interview_node(_state(assistant_type="interview_evaluator"))

    assert update == {"phase": "select_interview"}
    assert not created
    assert "didn't catch" in messages[-1]


@pytest.mark.asyncio
async def test_skip_moves_on_without_a_round(monkeypatch):
    _, created, _ = _patch(monkeypatch, reply="skip", rounds=[ROUND])

    update = await si.select_interview_node(_state(assistant_type="interview_evaluator"))

    assert update == {"phase": "evaluator_context"}
    assert not created


@pytest.mark.asyncio
async def test_no_journey_still_classifies_without_persisting(monkeypatch):
    _, created, _ = _patch(monkeypatch, reply="panel")

    state = ApplicationState(session_id="s1", assistant_type="interview_evaluator")
    update = await si.select_interview_node(state)

    assert update["interview_type"] == "panel"
    assert update["interview_id"] is None
    assert not created
