"""POST /journeys/{id}/outcome — the date and the reason, written as one act.

The endpoint exists so `job_feedback.outcome` can be derived rather than chosen.
Deriving it is only safe if the date is already on the row when the feedback is
written, which is what "one call writes both" buys.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.routes import router
from backend.storage.feedback import list_feedback
from backend.storage.interviews import create_interview, update_interview
from backend.storage.journeys import create_journey, get_journey


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _job(profile_id: str | None = "p1") -> str:
    return await create_journey(
        profile_id=profile_id, company_name="voize", job_title="Head of Data & AI"
    )


# --- the date and the reason together -------------------------------------


async def test_rejection_writes_the_date_and_the_reason(client):
    jid = await _job()

    r = await client.post(
        f"/api/journeys/{jid}/outcome",
        json={
            "kind": "rejected",
            "date": 1758067200.0,
            "feedback_text": "  Wanted someone who had built a team from scratch.  ",
            "source": "hiring_manager",
        },
    )

    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert (await get_journey(jid))["rejected_at"] == 1758067200.0

    entry = (await list_feedback(jid))[0]
    assert entry["feedback_text"] == "Wanted someone who had built a team from scratch."
    assert entry["source"] == "hiring_manager"


async def test_the_snapshot_agrees_with_the_date_just_written(client):
    """The whole point: the feedback row sees the rejection the same call wrote."""
    jid = await _job()

    await client.post(
        f"/api/journeys/{jid}/outcome",
        json={"kind": "rejected", "feedback_text": "No fit."},
    )

    assert (await list_feedback(jid))[0]["outcome"] == "rejected"


@pytest.mark.parametrize(
    ("kind", "column", "status"),
    [
        ("rejected", "rejected_at", "rejected"),
        ("offer", "offer_at", "offer"),
        ("withdrawn", "dropped_at", "dropped"),
        ("on_hold", "on_hold_at", "on_hold"),
    ],
)
async def test_each_outcome_writes_its_own_date(client, kind, column, status):
    jid = await _job()
    await client.post(f"/api/journeys/{jid}/outcome", json={"kind": kind, "date": 1758067200.0})

    journey = await get_journey(jid)
    assert journey[column] == 1758067200.0
    assert (await client.get(f"/api/journeys/{jid}")).json()["status"] == status


async def test_an_offer_snapshots_as_an_offer(client):
    jid = await _job()

    await client.post(
        f"/api/journeys/{jid}/outcome",
        json={"kind": "offer", "feedback_text": "Delighted to make you an offer."},
    )

    assert (await list_feedback(jid))[0]["outcome"] == "offer"


async def test_a_hold_leaves_the_outcome_empty(client):
    """On hold is not an ending, so there is no outcome to snapshot yet."""
    jid = await _job()

    await client.post(
        f"/api/journeys/{jid}/outcome",
        json={"kind": "on_hold", "feedback_text": "Budget frozen until Q1."},
    )

    assert (await list_feedback(jid))[0]["outcome"] == ""


# --- the reason is optional -----------------------------------------------


async def test_no_reason_writes_the_date_and_no_feedback_row(client):
    jid = await _job()

    r = await client.post(f"/api/journeys/{jid}/outcome", json={"kind": "rejected"})

    assert r.status_code == 200
    assert (await get_journey(jid))["rejected_at"] is not None
    assert await list_feedback(jid) == []


async def test_whitespace_only_reason_is_not_a_reason(client):
    jid = await _job()

    await client.post(
        f"/api/journeys/{jid}/outcome", json={"kind": "rejected", "feedback_text": "   \n  "}
    )

    assert await list_feedback(jid) == []


async def test_the_date_defaults_to_now(client):
    jid = await _job()

    await client.post(f"/api/journeys/{jid}/outcome", json={"kind": "rejected"})

    assert (await get_journey(jid))["rejected_at"] > 0


# --- stage inference ------------------------------------------------------


async def test_stage_is_inferred_from_the_last_round(client):
    jid = await _job()
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="final")
    await update_interview(iid, scheduled_at=1758000000.0)

    await client.post(
        f"/api/journeys/{jid}/outcome", json={"kind": "rejected", "feedback_text": "Close call."}
    )

    assert (await list_feedback(jid))[0]["stage"] == "final"


async def test_stage_is_unknown_when_no_round_happened(client):
    jid = await _job()

    await client.post(
        f"/api/journeys/{jid}/outcome", json={"kind": "rejected", "feedback_text": "No fit."}
    )

    assert (await list_feedback(jid))[0]["stage"] == "unknown"


# --- rejections -----------------------------------------------------------


async def test_unknown_kind_is_rejected(client):
    jid = await _job()

    r = await client.post(f"/api/journeys/{jid}/outcome", json={"kind": "ghosted"})

    assert r.status_code == 400
    assert (await get_journey(jid))["rejected_at"] is None


async def test_outcome_cannot_be_supplied_by_the_client(client):
    jid = await _job()

    r = await client.post(
        f"/api/journeys/{jid}/outcome",
        json={"kind": "rejected", "outcome": "offer", "feedback_text": "t"},
    )

    assert r.status_code == 422


async def test_unknown_journey_is_404(client):
    r = await client.post("/api/journeys/nope/outcome", json={"kind": "rejected"})

    assert r.status_code == 404


async def test_unknown_source_is_rejected_and_leaves_no_feedback(client):
    jid = await _job()

    r = await client.post(
        f"/api/journeys/{jid}/outcome",
        json={"kind": "rejected", "feedback_text": "t", "source": "linkedin"},
    )

    assert r.status_code == 400
    assert await list_feedback(jid) == []


# --- feedback with no outcome ---------------------------------------------


async def test_midprocess_feedback_snapshots_empty(client):
    """A recruiter's aside during a live process has no outcome to record."""
    jid = await _job()
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="screening")
    await update_interview(iid, scheduled_at=1758000000.0)

    await client.post(
        f"/api/journeys/{jid}/feedback",
        json={"feedback_text": "They liked the platform work.", "stage": "screening"},
    )

    assert (await list_feedback(jid))[0]["outcome"] == ""
