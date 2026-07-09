import time

import pytest

import backend.storage.db as db_module
from backend.storage.journeys import (
    create_journey,
    delete_journey,
    find_journey,
    get_journey,
    list_journeys,
    update_journey,
)


@pytest.mark.asyncio
async def test_create_and_get_roundtrip(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    journey = await get_journey(jid)

    assert journey is not None
    assert journey["journey_id"] == jid
    assert journey["profile_id"] == "p1"
    assert journey["company_name"] == "ACME"
    assert journey["job_title"] == "Engineer"
    assert journey["created_at"] == journey["updated_at"]


@pytest.mark.asyncio
async def test_get_missing_returns_none(test_db):
    assert await get_journey("does-not-exist") is None


@pytest.mark.asyncio
async def test_update_sets_fields_and_bumps_updated_at(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    before = await get_journey(jid)

    time.sleep(0.01)
    await update_journey(jid, cover_letter="Dear ACME, ...")
    after = await get_journey(jid)

    assert after["cover_letter"] == "Dear ACME, ..."
    assert after["updated_at"] > before["updated_at"]
    assert after["created_at"] == before["created_at"]


@pytest.mark.asyncio
async def test_update_unknown_field_raises(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    with pytest.raises(ValueError):
        await update_journey(jid, not_a_real_field="x")


@pytest.mark.asyncio
async def test_create_unknown_field_raises(test_db):
    with pytest.raises(ValueError):
        await create_journey(profile_id="p1", not_a_real_field="x")


@pytest.mark.asyncio
async def test_find_by_job_url(test_db):
    await create_journey(
        profile_id="p1",
        job_url="https://example.com/job/1",
        company_name="ACME",
        job_title="Engineer",
    )
    found = await find_journey(
        profile_id="p1", job_url="https://example.com/job/1", company_name="", job_title=""
    )
    assert found is not None
    assert found["company_name"] == "ACME"


@pytest.mark.asyncio
async def test_find_by_company_and_title_case_insensitive(test_db):
    await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    found = await find_journey(
        profile_id="p1", job_url="", company_name="acme", job_title="engineer"
    )
    assert found is not None
    assert found["company_name"] == "ACME"


@pytest.mark.asyncio
async def test_find_no_match_returns_none(test_db):
    found = await find_journey(
        profile_id="p1", job_url="", company_name="Nope", job_title="Nothing"
    )
    assert found is None


@pytest.mark.asyncio
async def test_list_ordering_most_recent_first(test_db):
    j1 = await create_journey(profile_id="p1", company_name="First", job_title="A")
    time.sleep(0.01)
    j2 = await create_journey(profile_id="p1", company_name="Second", job_title="B")

    journeys = await list_journeys(profile_id="p1")
    assert [j["journey_id"] for j in journeys] == [j2, j1]


@pytest.mark.asyncio
async def test_list_profile_filter(test_db):
    await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")
    await create_journey(profile_id="p2", company_name="Other Co", job_title="Manager")

    assert len(await list_journeys(profile_id="p1")) == 1
    assert len(await list_journeys(profile_id="p2")) == 1
    assert len(await list_journeys(profile_id=None)) == 2


@pytest.mark.asyncio
async def test_list_query_filter(test_db):
    await create_journey(profile_id="p1", company_name="ACME Corp", job_title="Engineer")
    await create_journey(profile_id="p1", company_name="Other Co", job_title="Manager")

    matches = await list_journeys(profile_id="p1", query="acme")
    assert len(matches) == 1
    assert matches[0]["company_name"] == "ACME Corp"

    title_matches = await list_journeys(profile_id="p1", query="manager")
    assert len(title_matches) == 1
    assert title_matches[0]["job_title"] == "Manager"


@pytest.mark.asyncio
async def test_list_limit(test_db):
    for i in range(5):
        await create_journey(profile_id="p1", company_name=f"Co{i}", job_title="Role")

    assert len(await list_journeys(profile_id="p1", limit=3)) == 3


@pytest.mark.asyncio
async def test_delete_removes_row(test_db):
    jid = await create_journey(profile_id="p1", company_name="ACME", job_title="Engineer")

    assert await delete_journey(jid) is True
    assert await get_journey(jid) is None
    assert await delete_journey(jid) is False


@pytest.mark.asyncio
async def test_backfill_from_application_records(test_db):
    async with db_module.connect() as db:
        await db.execute(
            """
            INSERT INTO application_records
                (profile_id, session_id, job_title, company_name, job_source_type,
                 initial_cl, final_cl, revision_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("p1", "s1", "Engineer", "ACME", "url", "draft", "final v1", 0, 1000.0),
        )
        await db.execute(
            """
            INSERT INTO application_records
                (profile_id, session_id, job_title, company_name, job_source_type,
                 initial_cl, final_cl, revision_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("p1", "s2", "Engineer", "ACME", "url", "draft", "final v2", 1, 2000.0),
        )
        await db.commit()

    await db_module.init_db()
    await db_module.init_db()

    journeys = await list_journeys(profile_id="p1")
    assert len(journeys) == 1
    assert journeys[0]["cover_letter"] == "final v2"
    assert journeys[0]["company_name"] == "ACME"
