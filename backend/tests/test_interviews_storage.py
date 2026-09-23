"""Tests for the per-round job_interviews storage layer."""

import aiosqlite
import pytest

from backend.storage.db import SCHEMA, _migrate
from backend.storage.interviews import (
    create_interview,
    delete_interview,
    describe_type,
    get_interview,
    list_interviews,
    resolve_type,
    type_label,
    update_interview,
)
from backend.storage.journeys import create_journey


@pytest.mark.asyncio
async def test_create_and_get(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    iid = await create_interview(
        journey_id=jid, profile_id="p1", interview_type="technical", label="pair session"
    )
    row = await get_interview(iid)
    assert row["journey_id"] == jid
    assert row["interview_type"] == "technical"
    assert row["label"] == "pair session"
    assert row["briefing"] == ""
    assert row["briefing_at"] is None


@pytest.mark.asyncio
async def test_briefing_write_stamps_time(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="screening")

    await update_interview(iid, briefing="Prep notes")
    row = await get_interview(iid)
    assert row["briefing"] == "Prep notes"
    assert row["briefing_at"] is not None
    assert row["evaluation_at"] is None

    await update_interview(iid, evaluation_summary='{"overall_score": 7}')
    row = await get_interview(iid)
    assert row["evaluation_at"] is not None


@pytest.mark.asyncio
async def test_list_is_scoped_to_journey_and_ordered(test_db):
    j1 = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    j2 = await create_journey(profile_id="p1", company_name="Other", job_title="Manager")
    first = await create_interview(journey_id=j1, profile_id="p1", interview_type="recruiter")
    second = await create_interview(journey_id=j1, profile_id="p1", interview_type="technical")
    await create_interview(journey_id=j2, profile_id="p1", interview_type="screening")

    rounds = await list_interviews(j1)
    assert [r["interview_id"] for r in rounds] == [first, second]


@pytest.mark.asyncio
async def test_delete_removes_one_round_only(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    kept = await create_interview(journey_id=jid, profile_id="p1", interview_type="recruiter")
    doomed = await create_interview(journey_id=jid, profile_id="p1", interview_type="screening")

    assert await delete_interview(doomed) is True
    assert await get_interview(doomed) is None
    assert [r["interview_id"] for r in await list_interviews(jid)] == [kept]


@pytest.mark.asyncio
async def test_delete_of_an_unknown_round_is_false(test_db):
    assert await delete_interview("no-such-round") is False


@pytest.mark.asyncio
async def test_unknown_field_rejected(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    with pytest.raises(ValueError):
        await create_interview(journey_id=jid, profile_id="p1", not_a_real_field="x")
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="panel")
    with pytest.raises(ValueError):
        await update_interview(iid, not_a_real_field="x")


@pytest.mark.asyncio
async def test_migration_backfills_existing_journey_briefing(tmp_path, monkeypatch):
    """A journey briefed before per-round tracking becomes one 'other' round."""
    import backend.storage.db as db_module

    path = tmp_path / "backfill.sqlite"
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await _migrate(db)
        await db.execute(
            "INSERT INTO job_journeys (journey_id, profile_id, company_name, job_title,"
            " interview_briefing, interview_briefing_at, created_at, updated_at)"
            " VALUES ('j-old', 'p1', 'ACME', 'Engineer', 'Old briefing', 900.0, 800.0, 950.0)"
        )
        await db.commit()
        await _migrate(db)  # the run that performs the backfill
        await _migrate(db)  # idempotent: must not duplicate the round
        await db.commit()
    monkeypatch.setattr(db_module, "DB_PATH", path)

    rounds = await list_interviews("j-old")
    assert len(rounds) == 1
    assert rounds[0]["interview_type"] == "other"
    assert rounds[0]["briefing"] == "Old briefing"
    assert rounds[0]["briefing_at"] == 900.0


# ---- taxonomy helpers --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("technical", "technical"),
        ("Technical", "technical"),
        ("hiring manager", "hiring_manager"),
        ("HM", "hiring_manager"),
        ("Case study / presentation", "case_study"),
        ("team/peer", "team_peer"),
        ("tech", "technical"),
        ("", None),
        ("something else entirely", None),
    ],
)
def test_resolve_type(text, expected):
    assert resolve_type(text) == expected


def test_labels_and_description():
    assert type_label("hiring_manager") == "Hiring manager"
    assert describe_type("") == ""
    described = describe_type("technical", "pair session")
    assert described.startswith("Technical — ")
    assert "pair session" in described
