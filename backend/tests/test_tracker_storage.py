"""Tracker persistence: the event log, the journey date columns, and the
migration that gives existing journeys dates to be derived from."""

import time
import uuid

import pytest

import backend.storage.db as db_module
from backend.storage.db import connect
from backend.storage.events import add_event, delete_event, list_events, update_event
from backend.storage.interviews import create_interview, get_interview, list_interviews
from backend.storage.journeys import (
    create_journey,
    delete_journey,
    derive_status,
    get_journey,
    list_journeys,
    update_journey,
)

DAY = 86_400.0
# The `silent` rung reads the clock, so status assertions pin one. Ten days in:
# past the fixtures below, well inside the quiet window.
NOW = 10 * DAY


def _status(journey: dict, rounds=()) -> str:
    return derive_status(journey, list(rounds), now=NOW)


async def _legacy_feedback(journey_id: str, outcome: str) -> None:
    """A feedback row as versions before v0.13.0 wrote it, with a caller-chosen
    outcome. The backfill migration exists for exactly these rows — `add_feedback`
    derives the outcome now, so it can no longer produce one."""
    async with connect() as db:
        await db.execute(
            "INSERT INTO job_feedback (feedback_id, journey_id, profile_id, interview_ids,"
            " stage, outcome, source, feedback_text, created_at)"
            " VALUES (?, ?, 'p1', '[]', 'final', ?, 'recruiter', '…', ?)",
            (uuid.uuid4().hex, journey_id, outcome, time.time()),
        )
        await db.commit()


# --- dates on the journey ---------------------------------------------------


async def test_tracker_dates_roundtrip(test_db):
    jid = await create_journey(
        profile_id="p1", company_name="ACME", job_title="Engineer", applied_at=DAY
    )
    assert (await get_journey(jid))["applied_at"] == DAY

    await update_journey(jid, rejected_at=5 * DAY, notes="No reasons given.")
    journey = await get_journey(jid)
    assert journey["rejected_at"] == 5 * DAY
    assert journey["notes"] == "No reasons given."


async def test_clearing_a_date_moves_the_status_back(test_db):
    jid = await create_journey(
        profile_id="p1", company_name="ACME", job_title="Engineer",
        applied_at=DAY, rejected_at=5 * DAY,
    )
    rounds = await list_interviews(jid)
    assert _status(await get_journey(jid), rounds) == "rejected"

    await update_journey(jid, rejected_at=None)
    assert _status(await get_journey(jid), rounds) == "applied"


async def test_new_journey_has_no_dates_and_reads_draft(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    journey = await get_journey(jid)
    assert journey["applied_at"] is None
    assert journey["notes"] == ""
    assert _status(journey, []) == "draft"


async def test_list_journeys_unbounded(test_db):
    for i in range(12):
        await create_journey(profile_id="p1", company_name=f"Co{i}", job_title="Role")

    assert len(await list_journeys(profile_id="p1")) == 10  # default page
    assert len(await list_journeys(profile_id="p1", limit=None)) == 12


# --- rounds carry a date ----------------------------------------------------


async def test_created_round_is_dated_so_the_job_reads_in_progress(test_db):
    jid = await create_journey(
        profile_id="p1", company_name="ACME", job_title="Engineer", applied_at=DAY
    )
    await create_interview(journey_id=jid, profile_id="p1", interview_type="screening")

    rounds = await list_interviews(jid)
    assert rounds[0]["scheduled_at"] is not None
    assert _status(await get_journey(jid), rounds) == "in_progress"


async def test_round_date_is_correctable(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    iid = await create_interview(
        journey_id=jid, profile_id="p1", interview_type="technical", scheduled_at=2 * DAY
    )
    assert (await get_interview(iid))["scheduled_at"] == 2 * DAY

    from backend.storage.interviews import update_interview

    await update_interview(iid, scheduled_at=9 * DAY)
    assert (await get_interview(iid))["scheduled_at"] == 9 * DAY


# --- events -----------------------------------------------------------------


async def test_event_roundtrip_newest_first(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await add_event(journey_id=jid, occurred_at=DAY, text="Applied via careers page.")
    await add_event(
        journey_id=jid, occurred_at=3 * DAY, text="Sent a follow-up.", kind="follow_up"
    )

    events = await list_events(jid)
    assert [e["text"] for e in events] == ["Sent a follow-up.", "Applied via careers page."]
    assert events[0]["kind"] == "follow_up"


async def test_unknown_event_kind_raises(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    with pytest.raises(ValueError):
        await add_event(journey_id=jid, occurred_at=DAY, kind="not_a_kind")

    eid = await add_event(journey_id=jid, occurred_at=DAY, text="x")
    with pytest.raises(ValueError):
        await update_event(eid, kind="not_a_kind")


async def test_update_event_unknown_field_raises(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    eid = await add_event(journey_id=jid, occurred_at=DAY, text="x")
    with pytest.raises(ValueError):
        await update_event(eid, journey_id="somewhere-else")


async def test_update_and_delete_event(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    eid = await add_event(journey_id=jid, occurred_at=DAY, text="Recruiter called.")

    await update_event(eid, text="Recruiter called on WhatsApp.", occurred_at=2 * DAY)
    event = (await list_events(jid))[0]
    assert event["text"] == "Recruiter called on WhatsApp."
    assert event["occurred_at"] == 2 * DAY

    assert await delete_event(eid) is True
    assert await list_events(jid) == []
    assert await delete_event(eid) is False


async def test_events_do_not_affect_status(test_db):
    """Events are a log, not evidence. Only dates move the status."""
    jid = await create_journey(
        profile_id="p1", company_name="ACME", job_title="Engineer", applied_at=DAY
    )
    await add_event(journey_id=jid, occurred_at=2 * DAY, text="Invited to interview.")
    assert _status(await get_journey(jid), await list_interviews(jid)) == "applied"


async def test_deleting_a_journey_takes_its_events(test_db):
    """foreign_keys is off, so the cascade has to be explicit."""
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await add_event(journey_id=jid, occurred_at=DAY, text="Applied.")

    await delete_journey(jid)
    assert await list_events(jid) == []


# --- migration backfill -----------------------------------------------------


async def test_backfill_gives_existing_journeys_a_submission_date(test_db):
    jid = await create_journey(
        profile_id="p1", company_name="ACME", job_title="Engineer", cover_letter="Dear ACME"
    )
    await update_journey(jid, applied_at=None)

    await db_module.init_db()

    journey = await get_journey(jid)
    assert journey["applied_at"] == journey["cover_letter_at"]
    assert _status(journey, []) == "applied"


async def test_backfill_dates_existing_rounds(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    iid = await create_interview(journey_id=jid, profile_id="p1", interview_type="screening")
    async with db_module.connect() as db:
        await db.execute(
            "UPDATE job_interviews SET scheduled_at = NULL WHERE interview_id = ?", (iid,)
        )
        await db.commit()

    await db_module.init_db()

    round_ = await get_interview(iid)
    assert round_["scheduled_at"] == round_["created_at"]


async def test_backfill_maps_feedback_outcomes_onto_dates(test_db):
    rejected = await create_journey(profile_id="p1", company_name="A", job_title="R")
    offered = await create_journey(profile_id="p1", company_name="B", job_title="O")
    withdrew = await create_journey(profile_id="p1", company_name="C", job_title="W")
    ghosted = await create_journey(profile_id="p1", company_name="D", job_title="G")

    for jid, outcome in (
        (rejected, "rejected"),
        (offered, "offer"),
        (withdrew, "withdrawn"),
        (ghosted, "ghosted"),
    ):
        await _legacy_feedback(jid, outcome)

    await db_module.init_db()

    assert (await get_journey(rejected))["rejected_at"] is not None
    assert (await get_journey(offered))["offer_at"] is not None
    assert (await get_journey(withdrew))["dropped_at"] is not None

    # No response is not an outcome date — that row stays Applied.
    ghosted_row = await get_journey(ghosted)
    assert ghosted_row["rejected_at"] is None
    assert ghosted_row["dropped_at"] is None
    assert _status(ghosted_row, []) == "applied"


async def test_backfill_is_idempotent_and_never_overwrites_a_correction(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await _legacy_feedback(jid, "rejected")
    await db_module.init_db()

    await update_journey(jid, rejected_at=12345.0, applied_at=999.0)
    await db_module.init_db()
    await db_module.init_db()

    journey = await get_journey(jid)
    assert journey["rejected_at"] == 12345.0
    assert journey["applied_at"] == 999.0
