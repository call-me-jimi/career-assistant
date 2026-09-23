"""Tracker endpoints: create, patch dates, rounds and events, and the derived
status that comes back on every response."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.api.routes as routes
from backend.api.routes import router
from backend.storage.events import list_events
from backend.storage.interviews import create_interview, get_interview, list_interviews
from backend.storage.journeys import create_journey, get_journey

DAY = 86_400.0


@pytest.fixture(autouse=True)
def never_quiet(monkeypatch):
    """These tests date applications at the epoch and none of them is about
    silence, so widen the quiet window out of the way. `silent` has its own
    coverage in test_tracker_status.py and test_tracker_summary.py."""
    real = routes.load_settings

    def wide():
        settings = real()
        settings.quiet_after_days = 10**6
        return settings

    monkeypatch.setattr(routes, "load_settings", wide)


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _job(**fields) -> str:
    return await create_journey(
        profile_id="p1", company_name="ACME", job_title="Staff Engineer", **fields
    )


# --- list -------------------------------------------------------------------


async def test_list_returns_status_rounds_and_events(client):
    jid = await _job(applied_at=DAY)
    await create_interview(
        journey_id=jid, profile_id="p1", interview_type="screening", scheduled_at=2 * DAY
    )
    await client.post(
        f"/api/journeys/{jid}/events", json={"occurred_at": 3 * DAY, "text": "Followed up."}
    )

    r = await client.get("/api/journeys")
    row = r.json()["journeys"][0]

    assert row["status"] == "in_progress"
    assert row["interviews"][0]["type_label"] == "Screening"
    assert [e["text"] for e in row["events"]] == ["Followed up."]


async def test_list_is_not_capped_at_ten(client):
    for i in range(12):
        await create_journey(profile_id="p1", company_name=f"Co{i}", job_title="Role")

    r = await client.get("/api/journeys")
    assert len(r.json()["journeys"]) == 12


# --- create -----------------------------------------------------------------


async def test_post_creates_a_tracked_job(client):
    r = await client.post(
        "/api/journeys",
        json={
            "profile_id": "p1",
            "job_title": "Head of Data",
            "company_name": "BeReal",
            "location": "Paris",
            "applied_at": DAY,
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["company_name"] == "BeReal"
    assert body["status"] == "applied"
    assert (await get_journey(body["journey_id"]))["location"] == "Paris"


async def test_post_without_dates_is_draft(client):
    r = await client.post("/api/journeys", json={"company_name": "Yepoda"})
    assert r.json()["status"] == "draft"


# --- patch ------------------------------------------------------------------


async def test_patch_sets_a_date_and_moves_the_status(client):
    jid = await _job(applied_at=DAY)

    r = await client.patch(f"/api/journeys/{jid}", json={"rejected_at": 5 * DAY})

    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert (await get_journey(jid))["rejected_at"] == 5 * DAY


async def test_patch_null_clears_a_date_and_moves_it_back(client):
    jid = await _job(applied_at=DAY, rejected_at=5 * DAY)

    r = await client.patch(f"/api/journeys/{jid}", json={"rejected_at": None})

    assert r.json()["status"] == "applied"
    assert (await get_journey(jid))["rejected_at"] is None


async def test_patch_leaves_omitted_fields_alone(client):
    jid = await _job(applied_at=DAY, notes="Applied via careers page.")

    await client.patch(f"/api/journeys/{jid}", json={"location": "Berlin"})

    journey = await get_journey(jid)
    assert journey["location"] == "Berlin"
    assert journey["notes"] == "Applied via careers page."
    assert journey["applied_at"] == DAY


async def test_patch_status_is_ignored_it_is_not_writable(client):
    jid = await _job(applied_at=DAY)

    r = await client.patch(f"/api/journeys/{jid}", json={"status": "offer"})

    assert r.status_code == 200
    assert r.json()["status"] == "applied"


async def test_patch_missing_journey_404s(client):
    r = await client.patch("/api/journeys/nope", json={"notes": "x"})
    assert r.status_code == 404


# --- rounds -----------------------------------------------------------------


async def test_post_round_makes_the_job_in_progress(client):
    jid = await _job(applied_at=DAY)

    r = await client.post(
        f"/api/journeys/{jid}/interviews",
        json={"interview_type": "hiring_manager", "label": "VP Data", "scheduled_at": 4 * DAY},
    )

    assert r.status_code == 200
    detail = (await client.get(f"/api/journeys/{jid}")).json()
    assert detail["status"] == "in_progress"
    assert detail["interviews"][0]["type_label"] == "Hiring manager"
    assert detail["interviews"][0]["scheduled_at"] == 4 * DAY


async def test_post_round_accepts_an_alias(client):
    jid = await _job()
    r = await client.post(f"/api/journeys/{jid}/interviews", json={"interview_type": "hm"})

    interview = await get_interview(r.json()["interview_id"])
    assert interview["interview_type"] == "hiring_manager"


async def test_post_round_rejects_an_unknown_type(client):
    jid = await _job()
    r = await client.post(
        f"/api/journeys/{jid}/interviews", json={"interview_type": "vibes_check"}
    )
    assert r.status_code == 400


async def test_post_round_inherits_the_jobs_profile(client):
    jid = await _job()
    r = await client.post(
        f"/api/journeys/{jid}/interviews",
        json={"interview_type": "screening", "profile_id": "someone-else"},
    )
    assert (await get_interview(r.json()["interview_id"]))["profile_id"] == "p1"


async def test_patch_round_date_can_lift_a_hold(client):
    jid = await _job(applied_at=DAY, on_hold_at=5 * DAY)
    iid = await create_interview(
        journey_id=jid, profile_id="p1", interview_type="screening", scheduled_at=2 * DAY
    )
    assert (await client.get(f"/api/journeys/{jid}")).json()["status"] == "on_hold"

    r = await client.patch(
        f"/api/journeys/{jid}/interviews/{iid}", json={"scheduled_at": 9 * DAY}
    )

    assert r.json()["status"] == "in_progress"


async def test_patch_round_of_another_job_404s(client):
    mine = await _job()
    theirs = await create_journey(profile_id="p1", company_name="Other", job_title="Role")
    iid = await create_interview(
        journey_id=theirs, profile_id="p1", interview_type="screening"
    )

    r = await client.patch(
        f"/api/journeys/{mine}/interviews/{iid}", json={"scheduled_at": DAY}
    )
    assert r.status_code == 404


async def test_delete_round_drops_it_and_the_status_it_carried(client):
    jid = await _job(applied_at=DAY)
    iid = await create_interview(
        journey_id=jid, profile_id="p1", interview_type="screening", scheduled_at=2 * DAY
    )
    assert (await client.get(f"/api/journeys/{jid}")).json()["status"] == "in_progress"

    r = await client.delete(f"/api/journeys/{jid}/interviews/{iid}")

    assert r.status_code == 200
    assert await list_interviews(jid) == []
    assert (await client.get(f"/api/journeys/{jid}")).json()["status"] == "applied"


async def test_delete_round_of_another_job_404s(client):
    mine = await _job()
    theirs = await create_journey(profile_id="p1", company_name="Other", job_title="Role")
    iid = await create_interview(
        journey_id=theirs, profile_id="p1", interview_type="screening"
    )

    assert (await client.delete(f"/api/journeys/{mine}/interviews/{iid}")).status_code == 404
    assert await get_interview(iid) is not None


# --- events -----------------------------------------------------------------


async def test_event_crud(client):
    jid = await _job(applied_at=DAY)

    created = await client.post(
        f"/api/journeys/{jid}/events",
        json={"occurred_at": 2 * DAY, "text": "Recruiter called.", "kind": "contact"},
    )
    assert created.status_code == 200
    eid = created.json()["event_id"]

    patched = await client.patch(
        f"/api/journeys/{jid}/events/{eid}", json={"text": "Recruiter called on WhatsApp."}
    )
    assert patched.json()["events"][0]["text"] == "Recruiter called on WhatsApp."
    assert (await list_events(jid))[0]["occurred_at"] == 2 * DAY

    deleted = await client.delete(f"/api/journeys/{jid}/events/{eid}")
    assert deleted.status_code == 200
    assert await list_events(jid) == []


async def test_event_does_not_move_the_status(client):
    jid = await _job(applied_at=DAY)
    await client.post(
        f"/api/journeys/{jid}/events", json={"occurred_at": 9 * DAY, "text": "Interviewed!"}
    )

    assert (await client.get(f"/api/journeys/{jid}")).json()["status"] == "applied"


async def test_event_rejects_an_unknown_kind(client):
    jid = await _job()
    r = await client.post(
        f"/api/journeys/{jid}/events", json={"occurred_at": DAY, "kind": "telepathy"}
    )
    assert r.status_code == 400


async def test_event_of_another_job_404s(client):
    mine = await _job()
    theirs = await create_journey(profile_id="p1", company_name="Other", job_title="Role")
    created = await client.post(
        f"/api/journeys/{theirs}/events", json={"occurred_at": DAY, "text": "x"}
    )
    eid = created.json()["event_id"]

    assert (await client.delete(f"/api/journeys/{mine}/events/{eid}")).status_code == 404
    assert (
        await client.patch(f"/api/journeys/{mine}/events/{eid}", json={"text": "y"})
    ).status_code == 404


async def test_event_on_missing_journey_404s(client):
    r = await client.post("/api/journeys/nope/events", json={"occurred_at": DAY})
    assert r.status_code == 404


# --- detail keeps its existing shape ---------------------------------------


async def test_detail_still_carries_feedback_and_calibration(client):
    jid = await _job(applied_at=DAY)
    body = (await client.get(f"/api/journeys/{jid}")).json()

    assert body["feedback"] == []
    assert body["calibration"] == []
    assert body["status"] == "applied"
