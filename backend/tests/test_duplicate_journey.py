"""Re-applying to a company you have approached before."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.routes import router
from backend.storage.feedback import add_feedback, list_feedback, list_recent_feedback
from backend.storage.interviews import create_interview
from backend.storage.journeys import create_journey, get_journey, list_journeys


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _attempt() -> str:
    return await create_journey(
        profile_id="p1",
        company_name="Simon Kucher",
        job_title="Senior Manager — Data Science",
        location="Berlin",
        job_url="https://example.test/job",
        job_description="Build the analytics practice.",
        company_description="Pricing consultancy.",
        notes="Applied via the careers page.",
        cover_letter="Dear Simon Kucher",
        applied_at=1_750_000_000.0,
        rejected_at=1_755_000_000.0,
    )


async def test_duplicate_carries_the_posting_and_notes(client):
    original = await _attempt()

    copy = (await client.post(f"/api/journeys/{original}/duplicate")).json()

    assert copy["journey_id"] != original
    assert copy["company_name"] == "Simon Kucher"
    assert copy["job_title"] == "Senior Manager — Data Science"
    assert copy["job_description"] == "Build the analytics practice."
    assert copy["notes"] == "Applied via the careers page."
    assert copy["profile_id"] == "p1"


async def test_duplicate_leaves_the_last_attempt_behind(client):
    original = await _attempt()
    await create_interview(journey_id=original, profile_id="p1", interview_type="final")
    await add_feedback(
        journey_id=original, profile_id="p1", feedback_text="Wanted more pricing depth."
    )

    copy = (await client.post(f"/api/journeys/{original}/duplicate")).json()

    assert copy["status"] == "draft"
    assert copy["applied_at"] is None
    assert copy["rejected_at"] is None
    assert copy["cover_letter"] == ""
    assert copy["interviews"] == []
    assert copy["feedback"] == []


async def test_the_original_is_untouched(client):
    original = await _attempt()

    await client.post(f"/api/journeys/{original}/duplicate")

    still_there = await get_journey(original)
    assert still_there["rejected_at"] == 1_755_000_000.0
    assert still_there["cover_letter"] == "Dear Simon Kucher"
    assert len(await list_journeys(profile_id="p1", limit=None)) == 2


async def test_the_new_attempt_still_sees_what_they_said_last_time(client):
    """The point of duplicating: the next letter knows why the last one failed."""
    original = await _attempt()
    await add_feedback(
        journey_id=original, profile_id="p1", feedback_text="Wanted more pricing depth."
    )

    copy = (await client.post(f"/api/journeys/{original}/duplicate")).json()
    seen = await list_recent_feedback("p1", limit=5, company_name=copy["company_name"])

    assert [e["feedback_text"] for e in seen] == ["Wanted more pricing depth."]
    assert await list_feedback(copy["journey_id"]) == []


async def test_unknown_journey_is_404(client):
    r = await client.post("/api/journeys/nope/duplicate")

    assert r.status_code == 404
