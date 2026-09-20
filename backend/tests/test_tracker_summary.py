"""The landing-page counters and the Waiting column.

Both read the clock, so these tests date their fixtures relative to now rather
than to the epoch — the point is how old an application is, not when it was.
"""

import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.routes import router
from backend.storage.feedback import add_feedback
from backend.storage.interviews import create_interview
from backend.storage.journeys import create_journey

DAY = 86_400.0
NOW = time.time()


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _job(company: str, **fields) -> str:
    return await create_journey(
        profile_id="p1", company_name=company, job_title="Head of Data", **fields
    )


def _days_ago(n: float) -> float:
    return NOW - n * DAY


# --- the six counters -------------------------------------------------------


async def test_summary_counts_each_bucket(client):
    await _job("Fresh", applied_at=_days_ago(3))
    await _job("Quiet", applied_at=_days_ago(90))
    await _job("AlsoQuiet", applied_at=_days_ago(45))
    await _job("Held", applied_at=_days_ago(10), on_hold_at=_days_ago(5))
    await _job("Turned down", applied_at=_days_ago(60), rejected_at=_days_ago(10))
    await _job("Walked", applied_at=_days_ago(60), dropped_at=_days_ago(9))

    live = await _job("Talking", applied_at=_days_ago(20))
    await create_interview(
        journey_id=live, profile_id="p1", interview_type="screening",
        scheduled_at=_days_ago(4),
    )

    body = (await client.get("/api/journeys/summary")).json()

    assert body == {
        "total": 7,
        "in_progress": 1,
        "quiet": 2,
        "on_hold": 1,
        "rejected": 1,
        "withdrawn": 1,
    }


async def test_summary_is_pooled_across_profiles(client):
    await create_journey(profile_id="head-of-data", company_name="A", job_title="R",
                         applied_at=_days_ago(90))
    await create_journey(profile_id="head-of-ai", company_name="B", job_title="R",
                         applied_at=_days_ago(90))

    body = (await client.get("/api/journeys/summary")).json()

    assert body["total"] == 2
    assert body["quiet"] == 2


async def test_summary_route_is_not_read_as_a_journey_id(client):
    """/journeys/summary must be declared before /journeys/{id}."""
    r = await client.get("/api/journeys/summary")

    assert r.status_code == 200
    assert "total" in r.json()


async def test_a_draft_counts_in_the_total_and_nowhere_else(client):
    await _job("Never sent")

    body = (await client.get("/api/journeys/summary")).json()

    assert body["total"] == 1
    assert body["quiet"] == 0
    assert body["in_progress"] == 0


# --- waiting on the row -----------------------------------------------------


async def test_rows_carry_waiting_days_and_last_contact(client):
    await _job("Quiet", applied_at=_days_ago(45))

    row = (await client.get("/api/journeys")).json()["journeys"][0]

    assert row["status"] == "silent"
    assert row["waiting_days"] == 45
    assert row["last_contact_at"] == pytest.approx(_days_ago(45))


async def test_a_round_is_the_last_contact(client):
    jid = await _job("Talking", applied_at=_days_ago(40))
    await create_interview(
        journey_id=jid, profile_id="p1", interview_type="screening",
        scheduled_at=_days_ago(2),
    )

    row = (await client.get("/api/journeys")).json()["journeys"][0]

    assert row["waiting_days"] == 2


async def test_something_they_said_is_contact_but_your_follow_up_is_not(client):
    """A follow-up you sent should not make a silent application look alive."""
    chased = await _job("Chased", applied_at=_days_ago(60))
    await client.post(
        f"/api/journeys/{chased}/events",
        json={"occurred_at": _days_ago(1), "text": "Sent a follow-up."},
    )

    answered = await _job("Answered", applied_at=_days_ago(60))
    await add_feedback(
        journey_id=answered, profile_id="p1", feedback_text="Still reviewing, sorry."
    )

    rows = {j["company_name"]: j for j in (await client.get("/api/journeys")).json()["journeys"]}

    assert rows["Chased"]["status"] == "silent"
    assert rows["Chased"]["waiting_days"] == 60
    assert rows["Answered"]["status"] == "applied"
    assert rows["Answered"]["waiting_days"] == 0


async def test_a_draft_has_no_waiting(client):
    await _job("Never sent")

    row = (await client.get("/api/journeys")).json()["journeys"][0]

    assert row["last_contact_at"] is None
    assert row["waiting_days"] is None
