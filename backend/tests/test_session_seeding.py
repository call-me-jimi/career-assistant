"""Launching an assistant from an application row.

The graph is unchanged: greeting, select_journey and select_interview each check
their own id and return early. What these cover is that the ids survive the trip
from POST /sessions into ApplicationState, and that each picker then declines to
ask for something already chosen.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.agent.nodes.greeting import greeting_node
from backend.agent.nodes.select_interview import select_interview_node
from backend.agent.nodes.select_journey import select_journey_node
from backend.agent.runner import _seed_from_session
from backend.agent.state import ApplicationState
from backend.storage.interviews import create_interview
from backend.storage.journeys import create_journey
from backend.storage.profiles import save_profile
from backend.storage.sessions import create_session, get_session


@pytest.fixture
async def client(test_db):
    from backend.api.routes import router

    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _job(**fields) -> str:
    return await create_journey(
        profile_id="p1",
        company_name="voize",
        job_title="Head of Data & AI",
        company_description="Healthcare speech AI.",
        **fields,
    )


# --- the ids survive the round trip ----------------------------------------


async def test_start_session_records_what_it_is_about(client):
    jid = await _job()
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="final")

    r = await client.post(
        "/api/sessions",
        json={"assistant_type": "interview_prep", "journey_id": jid, "interview_id": iid},
    )

    assert r.status_code == 200
    row = await get_session(r.json()["session_id"])
    assert row["journey_id"] == jid
    assert row["interview_id"] == iid
    assert row["profile_id"] == "p1"


async def test_plain_start_records_nothing(client):
    r = await client.post("/api/sessions", json={"assistant_type": "cover_letter"})

    row = await get_session(r.json()["session_id"])
    assert row["journey_id"] is None
    assert row["interview_id"] is None


async def test_the_jobs_owner_wins_over_the_client(client):
    jid = await _job()

    r = await client.post(
        "/api/sessions",
        json={"assistant_type": "cover_letter", "journey_id": jid, "profile_id": "someone-else"},
    )

    assert (await get_session(r.json()["session_id"]))["profile_id"] == "p1"


async def test_unknown_journey_is_404(client):
    r = await client.post("/api/sessions", json={"journey_id": "nope"})

    assert r.status_code == 404


async def test_a_round_from_another_job_is_rejected(client):
    mine = await _job()
    theirs = await _job()
    foreign = await create_interview(
        journey_id=theirs, profile_id="p1", interview_type="screening"
    )

    r = await client.post(
        "/api/sessions", json={"journey_id": mine, "interview_id": foreign}
    )

    assert r.status_code == 400


async def test_a_round_without_a_job_is_rejected(client):
    r = await client.post("/api/sessions", json={"interview_id": "loose"})

    assert r.status_code == 400


# --- the runner seeds the state --------------------------------------------


async def test_seed_carries_the_jobs_content(test_db):
    jid = await _job(cover_letter="Dear voize")
    sid = await create_session("cover_letter", "English", journey_id=jid, profile_id="p1")

    seed = await _seed_from_session(await get_session(sid))

    assert seed["journey_id"] == jid
    assert seed["profile_id"] == "p1"
    assert seed["company_name"] == "voize"
    assert seed["cover_letter"] == "Dear voize"


async def test_seed_is_empty_for_a_plain_session(test_db):
    sid = await create_session("cover_letter", "English")

    assert await _seed_from_session(await get_session(sid)) == {}


async def test_a_deleted_job_seeds_nothing_rather_than_crashing(test_db):
    sid = await create_session("cover_letter", "English", journey_id="gone")

    assert await _seed_from_session(await get_session(sid)) == {}


# --- the pickers decline to ask --------------------------------------------


async def test_select_journey_skips_straight_to_the_next_step(test_db):
    jid = await _job()
    state = ApplicationState(
        session_id="s1", assistant_type="interview_prep", journey_id=jid
    )

    # No interrupt: an unseeded call would block on the numbered picker.
    assert await select_journey_node(state) == {"phase": "interview_context"}


async def test_select_journey_still_asks_when_nothing_was_seeded(test_db):
    await _job()
    state = ApplicationState(session_id="s1", assistant_type="interview_prep")

    with pytest.raises(Exception):  # langgraph raises out of interrupt()
        await select_journey_node(state)


async def test_greeting_skips_the_profile_picker(test_db):
    await save_profile(
        profile_id="p1", name="Head of Data", applicant_name="Hendrik", cv_text="…",
        candidate_profile="…",
    )
    state = ApplicationState(session_id="s1", assistant_type="interview_prep", profile_id="p1")

    update = await greeting_node(state)

    assert update == {"applicant_name": "Hendrik", "phase": "cv_intake"}


async def test_select_interview_skips_when_the_round_is_known(test_db):
    jid = await _job()
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="final")
    state = ApplicationState(
        session_id="s1", assistant_type="interview_prep", journey_id=jid, interview_id=iid
    )

    assert await select_interview_node(state) == {"phase": "interview_briefing"}


async def test_select_interview_evaluator_lands_on_its_own_next_step(test_db):
    jid = await _job()
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="final")
    state = ApplicationState(
        session_id="s1", assistant_type="interview_evaluator", journey_id=jid, interview_id=iid
    )

    assert await select_interview_node(state) == {"phase": "evaluator_context"}


async def test_a_round_that_is_not_on_this_job_still_asks(test_db):
    jid = await _job()
    await create_interview(journey_id=jid, profile_id="p1", interview_type="final")
    state = ApplicationState(
        session_id="s1", assistant_type="interview_prep", journey_id=jid,
        interview_id="not-on-this-job",
    )

    with pytest.raises(Exception):
        await select_interview_node(state)
