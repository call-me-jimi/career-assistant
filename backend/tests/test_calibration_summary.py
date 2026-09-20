"""Is the evaluator honest?

Its mean score on rounds that advanced against rounds that were rejected. The
split comes from the job's dates, never from anything the evaluator was told —
an outcome must not reach it, only what an employer actually said.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.routes import router
from backend.storage.coaching_insights import save_coaching_insight
from backend.storage.feedback import add_feedback
from backend.storage.interviews import create_interview
from backend.storage.journeys import create_journey
from backend.storage.profiles import save_profile


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _profile() -> None:
    await save_profile(
        profile_id="p1", name="Head of Data", applicant_name="Hendrik",
        cv_text="…", candidate_profile="…",
    )


async def _evaluated_application(company: str, score: float, *, rejected: bool) -> None:
    """One application that got an evaluation and a reply, ending either way."""
    jid = await create_journey(
        profile_id="p1", company_name=company, job_title="Head of Data",
        applied_at=1_750_000_000.0,
        **({"rejected_at": 1_755_000_000.0} if rejected else {}),
    )
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="final")
    await save_coaching_insight(
        profile_id="p1",
        session_id=f"s-{company}",
        evaluation_dict={
            "overall_score": score,
            "decision": "lean_hire",
            "summary": "…",
            "weaknesses": ["vague on scope"],
            "improvements": ["quantify"],
        },
        job_title="Head of Data",
        company_name=company,
        journey_id=jid,
        interview_id=iid,
    )
    await add_feedback(
        journey_id=jid, profile_id="p1", interview_ids=[iid],
        feedback_text="They wanted someone who had built a team from scratch.",
    )


async def test_it_splits_verdicts_by_what_actually_happened(client):
    await _profile()
    await _evaluated_application("voize", 7.6, rejected=True)
    await _evaluated_application("DKB", 7.4, rejected=True)
    await _evaluated_application("nextbike", 8.2, rejected=False)

    body = (await client.get("/api/profiles/p1/calibration")).json()

    assert body["rejected"] == {"n": 2, "mean": 7.5}
    assert body["advanced"] == {"n": 1, "mean": 8.2}


async def test_it_is_empty_before_anything_has_run_its_course(client):
    await _profile()

    body = (await client.get("/api/profiles/p1/calibration")).json()

    assert body == {
        "advanced": {"n": 0, "mean": None},
        "rejected": {"n": 0, "mean": None},
    }


async def test_an_evaluation_with_no_reply_is_not_a_pair(client):
    """A verdict nobody answered calibrates nothing."""
    await _profile()
    jid = await create_journey(
        profile_id="p1", company_name="Silent", job_title="Head of Data",
        applied_at=1_750_000_000.0,
    )
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="final")
    await save_coaching_insight(
        profile_id="p1",
        session_id="s1",
        evaluation_dict={"overall_score": 9.0, "decision": "hire", "summary": "…"},
        job_title="Head of Data",
        company_name="Silent",
        journey_id=jid,
        interview_id=iid,
    )

    body = (await client.get("/api/profiles/p1/calibration")).json()

    assert body["advanced"]["n"] == 0
    assert body["rejected"]["n"] == 0


async def test_unknown_profile_is_404(client):
    r = await client.get("/api/profiles/nope/calibration")

    assert r.status_code == 404
