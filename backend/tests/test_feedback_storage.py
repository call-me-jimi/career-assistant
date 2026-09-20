import time

import pytest

from backend.storage.feedback import (
    add_feedback,
    delete_feedback,
    list_feedback,
    list_recent_feedback,
    render_feedback_for_prompt,
)
from backend.storage.journeys import create_journey, delete_journey


async def _job(company: str = "ACME", title: str = "Engineer", profile_id: str = "p1") -> str:
    return await create_journey(profile_id=profile_id, company_name=company, job_title=title)


@pytest.mark.asyncio
async def test_add_and_list_roundtrip(test_db):
    jid = await _job()
    fid = await add_feedback(
        journey_id=jid,
        profile_id="p1",
        interview_ids=["r1", "r2"],
        stage="final",
        source="recruiter",
        feedback_text="  Strong technically, unsure on stakeholder management.  ",
    )

    entries = await list_feedback(jid)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["feedback_id"] == fid
    assert entry["journey_id"] == jid
    assert entry["interview_ids"] == ["r1", "r2"]
    assert entry["stage"] == "final"
    # Derived from the job's dates, not the caller: this job has no outcome date.
    assert entry["outcome"] == ""
    assert entry["source"] == "recruiter"
    assert entry["feedback_text"] == "Strong technically, unsure on stakeholder management."


@pytest.mark.asyncio
async def test_defaults_cover_the_whole_process(test_db):
    jid = await _job()
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="No reason given.")

    entry = (await list_feedback(jid))[0]
    assert entry["interview_ids"] == []
    assert entry["stage"] == "unknown"
    assert entry["outcome"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"stage": "phone_screen"},
        {"source": "linkedin"},
    ],
)
async def test_unknown_enum_values_rejected(test_db, kwargs):
    jid = await _job()
    with pytest.raises(ValueError):
        await add_feedback(journey_id=jid, profile_id="p1", **kwargs)


@pytest.mark.asyncio
async def test_list_feedback_is_oldest_first(test_db):
    jid = await _job()
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="first")
    time.sleep(0.01)
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="second")

    assert [e["feedback_text"] for e in await list_feedback(jid)] == ["first", "second"]


@pytest.mark.asyncio
async def test_delete_feedback(test_db):
    jid = await _job()
    fid = await add_feedback(journey_id=jid, profile_id="p1", feedback_text="text")

    assert await delete_feedback(fid) is True
    assert await list_feedback(jid) == []
    assert await delete_feedback(fid) is False


@pytest.mark.asyncio
async def test_deleting_the_journey_removes_its_feedback(test_db):
    jid = await _job()
    other = await _job(company="Globex")
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="gone")
    await add_feedback(journey_id=other, profile_id="p1", feedback_text="kept")

    assert await delete_journey(jid) is True
    assert await list_feedback(jid) == []
    assert len(await list_feedback(other)) == 1


# --- list_recent_feedback -------------------------------------------------


@pytest.mark.asyncio
async def test_recent_is_profile_scoped(test_db):
    mine = await _job(profile_id="p1")
    theirs = await _job(company="Globex", profile_id="p2")
    await add_feedback(journey_id=mine, profile_id="p1", feedback_text="mine")
    await add_feedback(journey_id=theirs, profile_id="p2", feedback_text="theirs")

    assert [e["feedback_text"] for e in await list_recent_feedback("p1")] == ["mine"]


@pytest.mark.asyncio
async def test_recent_without_profile_returns_nothing(test_db):
    jid = await _job(profile_id="p1")
    await add_feedback(journey_id=jid, profile_id=None, feedback_text="orphan")

    assert await list_recent_feedback(None) == []
    assert await list_recent_feedback("") == []


@pytest.mark.asyncio
async def test_recent_skips_entries_with_no_text(test_db):
    jid = await _job()
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="   ")
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="said something")

    assert [e["feedback_text"] for e in await list_recent_feedback("p1")] == ["said something"]


@pytest.mark.asyncio
async def test_recent_is_newest_first_and_window_limited(test_db):
    jid = await _job()
    for n in range(4):
        await add_feedback(journey_id=jid, profile_id="p1", feedback_text=f"note {n}")
        time.sleep(0.01)

    recent = await list_recent_feedback("p1", limit=2)
    assert [e["feedback_text"] for e in recent] == ["note 3", "note 2"]


@pytest.mark.asyncio
async def test_recent_enriches_with_job_identity(test_db):
    jid = await _job(company="ACME", title="Staff Engineer")
    await add_feedback(journey_id=jid, profile_id="p1", feedback_text="note")

    entry = (await list_recent_feedback("p1"))[0]
    assert entry["company_name"] == "ACME"
    assert entry["job_title"] == "Staff Engineer"


@pytest.mark.asyncio
async def test_same_company_survives_the_window_and_sorts_first(test_db):
    acme = await _job(company="ACME")
    await add_feedback(journey_id=acme, profile_id="p1", feedback_text="acme said this")
    time.sleep(0.01)
    for n in range(3):
        other = await _job(company=f"Other {n}")
        await add_feedback(journey_id=other, profile_id="p1", feedback_text=f"other {n}")
        time.sleep(0.01)

    recent = await list_recent_feedback("p1", limit=2, company_name="acme")
    texts = [e["feedback_text"] for e in recent]

    # The ACME entry is the oldest of four and falls outside a window of 2, but is kept
    # anyway and sorts first. It takes priority *within* the window rather than adding to
    # it, so the window still bounds how much prompt budget this can consume.
    assert texts == ["acme said this", "other 2"]


@pytest.mark.asyncio
async def test_same_company_can_exceed_the_window(test_db):
    """The window never drops same-company feedback, even when there is a lot of it."""
    for n in range(3):
        acme = await _job(company="ACME")
        await add_feedback(journey_id=acme, profile_id="p1", feedback_text=f"acme {n}")
        time.sleep(0.01)
    other = await _job(company="Globex")
    await add_feedback(journey_id=other, profile_id="p1", feedback_text="globex")

    recent = await list_recent_feedback("p1", limit=2, company_name="ACME")

    assert [e["feedback_text"] for e in recent] == ["acme 2", "acme 1", "acme 0"]


# --- render_feedback_for_prompt -------------------------------------------


def test_render_empty_is_empty_string():
    assert render_feedback_for_prompt([]) == ""


def test_render_skips_entries_with_no_text():
    assert render_feedback_for_prompt([{"feedback_text": "  ", "company_name": "ACME"}]) == ""


def test_render_includes_identity_source_and_stage():
    rendered = render_feedback_for_prompt(
        [
            {
                "company_name": "ACME",
                "job_title": "Staff Engineer",
                "source": "hiring_manager",
                "stage": "final",
                "feedback_text": "Unsure on stakeholder management.",
                "created_at": time.time(),
            }
        ]
    )

    assert "ACME — Staff Engineer" in rendered
    assert "hiring manager" in rendered
    assert "after the final round" in rendered
    assert '"Unsure on stakeholder management."' in rendered


def test_render_omits_outcome():
    """A rejection is not evidence about performance; it never reaches a prompt."""
    rendered = render_feedback_for_prompt(
        [
            {
                "company_name": "ACME",
                "job_title": "Engineer",
                "outcome": "rejected",
                "feedback_text": "text",
                "created_at": time.time(),
            }
        ]
    )

    assert "rejected" not in rendered
