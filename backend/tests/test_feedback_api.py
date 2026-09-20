import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.routes import router
from backend.storage.coaching_insights import save_coaching_insight
from backend.storage.feedback import list_feedback
from backend.storage.interviews import create_interview
from backend.storage.journeys import create_journey


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _job(profile_id: str | None = "p1") -> str:
    return await create_journey(
        profile_id=profile_id, company_name="ACME", job_title="Staff Engineer"
    )


# --- POST -----------------------------------------------------------------


async def test_post_creates_feedback(client):
    jid = await _job()

    r = await client.post(
        f"/api/journeys/{jid}/feedback",
        json={
            "feedback_text": "Wanted sharper ownership stories.",
            "stage": "final",
            "source": "hiring_manager",
        },
    )

    assert r.status_code == 200
    entries = await list_feedback(jid)
    assert len(entries) == 1
    assert entries[0]["feedback_id"] == r.json()["feedback_id"]
    assert entries[0]["feedback_text"] == "Wanted sharper ownership stories."
    assert entries[0]["stage"] == "final"


async def test_post_defaults_to_the_whole_process(client):
    jid = await _job()

    r = await client.post(f"/api/journeys/{jid}/feedback", json={"feedback_text": "No reason."})

    assert r.status_code == 200
    assert (await list_feedback(jid))[0]["interview_ids"] == []


async def test_post_takes_profile_from_the_job_not_the_client(client):
    jid = await _job(profile_id="owner")

    # The payload forbids extras, so a smuggled profile_id is refused outright
    # rather than silently ignored.
    smuggled = await client.post(
        f"/api/journeys/{jid}/feedback",
        json={"feedback_text": "text", "profile_id": "attacker"},
    )
    assert smuggled.status_code == 422

    await client.post(f"/api/journeys/{jid}/feedback", json={"feedback_text": "text"})
    assert (await list_feedback(jid))[0]["profile_id"] == "owner"


async def test_post_accepts_rounds_belonging_to_the_job(client):
    jid = await _job()
    interview_id = await create_interview(
        journey_id=jid, profile_id="p1", interview_type="screening"
    )

    r = await client.post(
        f"/api/journeys/{jid}/feedback",
        json={"feedback_text": "Rushed.", "interview_ids": [interview_id]},
    )

    assert r.status_code == 200
    assert (await list_feedback(jid))[0]["interview_ids"] == [interview_id]


async def test_post_rejects_rounds_from_another_job(client):
    jid = await _job()
    other = await _job()
    foreign = await create_interview(
        journey_id=other, profile_id="p1", interview_type="screening"
    )

    r = await client.post(
        f"/api/journeys/{jid}/feedback",
        json={"feedback_text": "text", "interview_ids": [foreign]},
    )

    assert r.status_code == 400
    assert await list_feedback(jid) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"stage": "phone_screen"},
        {"source": "linkedin"},
    ],
)
async def test_post_rejects_unknown_enum_values(client, payload):
    jid = await _job()

    r = await client.post(f"/api/journeys/{jid}/feedback", json={"feedback_text": "t", **payload})

    assert r.status_code == 400
    assert await list_feedback(jid) == []


async def test_post_to_unknown_job_is_404(client):
    r = await client.post("/api/journeys/nope/feedback", json={"feedback_text": "text"})

    assert r.status_code == 404


# --- DELETE ---------------------------------------------------------------


async def test_delete_removes_the_entry(client):
    jid = await _job()
    post = await client.post(f"/api/journeys/{jid}/feedback", json={"feedback_text": "text"})
    feedback_id = post.json()["feedback_id"]

    r = await client.delete(f"/api/journeys/{jid}/feedback/{feedback_id}")

    assert r.status_code == 200
    assert await list_feedback(jid) == []


async def test_delete_unknown_entry_is_404(client):
    jid = await _job()

    r = await client.delete(f"/api/journeys/{jid}/feedback/nope")

    assert r.status_code == 404


async def test_delete_cannot_reach_another_jobs_feedback(client):
    jid = await _job()
    other = await _job()
    post = await client.post(f"/api/journeys/{other}/feedback", json={"feedback_text": "text"})
    feedback_id = post.json()["feedback_id"]

    r = await client.delete(f"/api/journeys/{jid}/feedback/{feedback_id}")

    assert r.status_code == 404
    assert len(await list_feedback(other)) == 1


# --- GET journey detail ---------------------------------------------------


async def test_detail_keeps_the_journey_fields_and_adds_the_new_ones(client):
    jid = await _job()

    body = (await client.get(f"/api/journeys/{jid}")).json()

    assert body["journey_id"] == jid
    assert body["company_name"] == "ACME"
    assert body["interviews"] == []
    assert body["feedback"] == []
    assert body["calibration"] == []


async def test_detail_lists_rounds_and_feedback(client):
    jid = await _job()
    await create_interview(journey_id=jid, profile_id="p1", interview_type="hiring_manager")
    await client.post(f"/api/journeys/{jid}/feedback", json={"feedback_text": "Close call."})

    body = (await client.get(f"/api/journeys/{jid}")).json()

    assert len(body["interviews"]) == 1
    assert body["interviews"][0]["interview_type"] == "hiring_manager"
    # The UI renders this instead of keeping its own copy of the round taxonomy.
    assert body["interviews"][0]["type_label"] == "Hiring manager"
    assert [e["feedback_text"] for e in body["feedback"]] == ["Close call."]


async def test_detail_pairs_evaluations_with_feedback(client):
    jid = await _job()
    interview_id = await create_interview(
        journey_id=jid, profile_id="p1", interview_type="hiring_manager"
    )
    await save_coaching_insight(
        profile_id="p1",
        session_id="s1",
        evaluation_dict={"overall_score": 7.2, "decision": "lean_hire", "weaknesses": ["vague"]},
        journey_id=jid,
        interview_id=interview_id,
    )
    await client.post(f"/api/journeys/{jid}/feedback", json={"feedback_text": "Wanted more depth."})

    body = (await client.get(f"/api/journeys/{jid}")).json()

    assert len(body["calibration"]) == 1
    pair = body["calibration"][0]
    assert pair["interview_id"] == interview_id
    assert pair["assistant_said"]["overall_score"] == 7.2
    assert pair["employer_said"] == "Wanted more depth."


async def test_detail_calibration_is_scoped_to_this_job(client):
    """Another job's pairs must not leak onto this job's page."""
    jid = await _job()
    other = await _job()
    other_round = await create_interview(
        journey_id=other, profile_id="p1", interview_type="screening"
    )
    await save_coaching_insight(
        profile_id="p1",
        session_id="s1",
        evaluation_dict={"overall_score": 5.0, "decision": "no_hire", "weaknesses": []},
        journey_id=other,
        interview_id=other_round,
    )
    await client.post(f"/api/journeys/{other}/feedback", json={"feedback_text": "Other job."})

    body = (await client.get(f"/api/journeys/{jid}")).json()

    assert body["calibration"] == []


async def test_detail_unknown_job_is_404(client):
    assert (await client.get("/api/journeys/nope")).status_code == 404
