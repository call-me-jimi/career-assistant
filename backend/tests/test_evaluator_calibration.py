import time

import aiosqlite
import pytest

from backend.storage.coaching_insights import save_coaching_insight
from backend.storage.db import SCHEMA, _migrate
from backend.storage.feedback import (
    add_feedback,
    list_evaluator_calibration,
    render_calibration_for_prompt,
)
from backend.storage.interviews import create_interview
from backend.storage.journeys import create_journey


async def _evaluated_round(
    journey_id: str,
    interview_type: str = "hiring_manager",
    *,
    profile_id: str = "p1",
    score: float = 7.2,
    decision: str = "lean_hire",
    weaknesses: list[str] | None = None,
) -> str:
    """A round that has been through the evaluator — the half a pair needs."""
    interview_id = await create_interview(
        journey_id=journey_id, profile_id=profile_id, interview_type=interview_type
    )
    await save_coaching_insight(
        profile_id=profile_id,
        session_id=f"s-{interview_id[:6]}",
        evaluation_dict={
            "overall_score": score,
            "decision": decision,
            "summary": "Solid but uneven.",
            "weaknesses": weaknesses if weaknesses is not None else ["vague on scope"],
            "improvements": ["quantify impact"],
        },
        journey_id=journey_id,
        interview_id=interview_id,
    )
    return interview_id


@pytest.mark.asyncio
async def test_whole_process_feedback_fans_out_to_every_evaluated_round(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await _evaluated_round(jid, "screening")
    await _evaluated_round(jid, "hiring_manager")
    await _evaluated_round(jid, "leadership")
    await add_feedback(
        journey_id=jid,
        profile_id="p1",
        interview_ids=[],
        source="recruiter",
        feedback_text="The panel liked the delivery record but wanted more strategic framing.",
    )

    pairs = await list_evaluator_calibration("p1", limit=10)

    assert len(pairs) == 3
    assert {p["employer_said"] for p in pairs} == {
        "The panel liked the delivery record but wanted more strategic framing."
    }
    rounds = " ".join(p["round"] for p in pairs)
    assert "Screening" in rounds and "Hiring manager" in rounds


@pytest.mark.asyncio
async def test_pinned_feedback_pairs_only_with_those_rounds(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    screening = await _evaluated_round(jid, "screening")
    await _evaluated_round(jid, "hiring_manager")
    await add_feedback(
        journey_id=jid,
        profile_id="p1",
        interview_ids=[screening],
        feedback_text="Screening call was rushed.",
    )

    pairs = await list_evaluator_calibration("p1", limit=10)

    assert len(pairs) == 1
    assert "Screening" in pairs[0]["round"]


@pytest.mark.asyncio
async def test_round_without_an_evaluation_produces_no_pair(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await create_interview(journey_id=jid, profile_id="p1", interview_type="screening")
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="Not a fit.")

    assert await list_evaluator_calibration("p1") == []


@pytest.mark.asyncio
async def test_feedback_without_an_evaluation_anywhere_produces_no_pair(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="Not a fit.")

    assert await list_evaluator_calibration("p1") == []


@pytest.mark.asyncio
async def test_evaluation_without_feedback_produces_no_pair(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await _evaluated_round(jid)

    assert await list_evaluator_calibration("p1") == []


@pytest.mark.asyncio
async def test_pre_migration_evaluations_are_skipped(test_db):
    """Rows written before journey_id existed can't be traced to a job."""
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await save_coaching_insight(
        profile_id="p1",
        session_id="legacy",
        evaluation_dict={"overall_score": 6.0, "decision": "no_hire", "weaknesses": []},
    )
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="Too junior.")

    assert await list_evaluator_calibration("p1") == []


@pytest.mark.asyncio
async def test_re_evaluated_round_uses_the_latest_verdict(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    interview_id = await _evaluated_round(jid, score=5.0)
    time.sleep(0.01)
    await save_coaching_insight(
        profile_id="p1",
        session_id="s2",
        evaluation_dict={"overall_score": 8.0, "decision": "hire", "weaknesses": []},
        journey_id=jid,
        interview_id=interview_id,
    )
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="Strong.")

    pairs = await list_evaluator_calibration("p1", limit=10)

    assert len(pairs) == 1
    assert pairs[0]["assistant_said"]["overall_score"] == 8.0


@pytest.mark.asyncio
async def test_pairs_carry_the_verdict_and_never_the_outcome(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await _evaluated_round(jid, weaknesses=["vague on scope"])
    await add_feedback(
        journey_id=jid,
        profile_id="p1",
        outcome="rejected",
        stage="final",
        source="hiring_manager",
        feedback_text="Wanted sharper ownership stories.",
    )

    pair = (await list_evaluator_calibration("p1"))[0]

    assert pair["company_name"] == "ACME"
    assert pair["assistant_said"]["decision"] == "lean_hire"
    assert pair["assistant_said"]["weaknesses"] == ["vague on scope"]
    assert pair["stage"] == "final"
    assert pair["source"] == "hiring_manager"
    assert "outcome" not in pair


@pytest.mark.asyncio
async def test_limit_caps_the_number_of_pairs(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    for kind in ("screening", "hiring_manager", "leadership"):
        await _evaluated_round(jid, kind)
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="Mixed signals.")

    assert len(await list_evaluator_calibration("p1", limit=2)) == 2


@pytest.mark.asyncio
async def test_is_profile_scoped_and_needs_a_profile(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await _evaluated_round(jid)
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="Too junior.")

    assert await list_evaluator_calibration("p2") == []
    assert await list_evaluator_calibration(None) == []
    assert await list_evaluator_calibration("") == []


@pytest.mark.asyncio
async def test_empty_feedback_text_produces_no_pair(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await _evaluated_round(jid)
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="   ")

    assert await list_evaluator_calibration("p1") == []


@pytest.mark.asyncio
async def test_migration_adds_the_columns_to_a_pre_existing_database(tmp_path):
    """Databases created before this feature take the ALTER path, not the SCHEMA path."""
    path = tmp_path / "old.sqlite"
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await db.execute("DROP TABLE coaching_insights")
        await db.execute(
            """
            CREATE TABLE coaching_insights (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id    TEXT NOT NULL,
                session_id    TEXT NOT NULL,
                job_title     TEXT NOT NULL DEFAULT '',
                company_name  TEXT NOT NULL DEFAULT '',
                overall_score REAL,
                decision      TEXT,
                summary       TEXT NOT NULL DEFAULT '',
                weaknesses    TEXT NOT NULL DEFAULT '[]',
                improvements  TEXT NOT NULL DEFAULT '[]',
                filler_words  TEXT NOT NULL DEFAULT '[]',
                pace          TEXT,
                clarity       TEXT,
                created_at    REAL NOT NULL
            )
            """
        )
        await db.execute(
            "INSERT INTO coaching_insights (profile_id, session_id, created_at) "
            "VALUES ('p1', 'legacy', 1.0)"
        )
        await db.commit()

    async with aiosqlite.connect(path) as db:
        await _migrate(db)
        await db.commit()
        cur = await db.execute("PRAGMA table_info(coaching_insights)")
        columns = {row[1] for row in await cur.fetchall()}
        cur = await db.execute(
            "SELECT journey_id, interview_id FROM coaching_insights WHERE session_id = 'legacy'"
        )
        legacy = await cur.fetchone()

    assert {"journey_id", "interview_id"} <= columns
    assert legacy == (None, None)


# --- render_calibration_for_prompt ----------------------------------------


def test_render_empty_is_empty_string():
    assert render_calibration_for_prompt([]) == ""


def test_render_shows_both_sides():
    rendered = render_calibration_for_prompt(
        [
            {
                "company_name": "ACME",
                "job_title": "Staff Engineer",
                "round": "Hiring manager interview — the manager's own read",
                "assistant_said": {
                    "overall_score": 7.2,
                    "decision": "lean_hire",
                    "summary": "Long free text that does not belong in the prompt.",
                    "weaknesses": ["vague on scope", "rushed closing"],
                },
                "employer_said": "Wanted sharper ownership stories.",
                "stage": "final",
                "source": "hiring_manager",
                "created_at": time.time(),
            }
        ]
    )

    assert "ACME — Staff Engineer" in rendered
    assert "7.2/10, lean_hire" in rendered
    assert "vague on scope; rushed closing" in rendered
    assert '"Wanted sharper ownership stories."' in rendered
    assert "hiring manager" in rendered
    assert "Long free text" not in rendered


def test_render_skips_pairs_with_nothing_said():
    assert render_calibration_for_prompt([{"company_name": "ACME", "employer_said": "  "}]) == ""
