"""The tracker questions the Cover Letter assistant asks before exporting:
free-text notes, and whether the application was actually submitted."""

import pytest

from backend.agent.nodes import log_application as mod
from backend.agent.state import ApplicationState
from backend.storage.journeys import create_journey, derive_status, get_journey


@pytest.fixture
def replies(monkeypatch):
    """Feed scripted answers to the node's successive interrupt() calls."""
    scripted: list[object] = []
    monkeypatch.setattr(mod, "emit_message", lambda *a, **k: None)
    monkeypatch.setattr(mod, "interrupt", lambda payload: scripted.pop(0))
    return scripted


async def _journey() -> str:
    return await create_journey(
        profile_id="p1", company_name="ACME", job_title="Engineer", cover_letter="Dear ACME"
    )


async def test_notes_and_submission_reach_the_journey(test_db, replies):
    jid = await _journey()
    state = ApplicationState(session_id="s", journey_id=jid)
    replies.extend(["applied on their job page. salary expectation: 120k", "yes"])

    update = await mod.log_application_node(state)

    journey = await get_journey(jid)
    assert journey["notes"] == "applied on their job page. salary expectation: 120k"
    assert journey["applied_at"] == update["applied_at"]
    assert derive_status(journey, []) == "applied"
    # The sheet row is built from the state, not the journey.
    assert update["application_notes"] == journey["notes"]


async def test_not_submitted_leaves_the_journey_a_draft(test_db, replies):
    jid = await _journey()
    state = ApplicationState(session_id="s", journey_id=jid)
    replies.extend(["applied via EasyApply on LinkedIn. no additional information.", "no"])

    update = await mod.log_application_node(state)

    journey = await get_journey(jid)
    assert journey["notes"].startswith("applied via EasyApply")
    assert journey["applied_at"] is None
    assert update["applied_at"] is None
    assert derive_status(journey, []) == "draft"


async def test_skipping_the_notes_writes_nothing(test_db, replies):
    jid = await _journey()
    state = ApplicationState(session_id="s", journey_id=jid)
    replies.extend(["skip", "no"])

    update = await mod.log_application_node(state)

    journey = await get_journey(jid)
    assert journey["notes"] == ""
    assert update["application_notes"] == ""
    assert update["application_logged"] is True


async def test_the_questions_are_asked_once(test_db, replies):
    """post_export can send the flow back through qa_menu for a second export.

    Nothing is scripted here, so a second round of questions would pop from an
    empty list and raise — and a 'yes' answered once must not be re-asked.
    """
    state = ApplicationState(session_id="s", journey_id=await _journey(), application_logged=True)

    assert await mod.log_application_node(state) == {}
