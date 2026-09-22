"""The one-off spreadsheet importer: column mapping, event parsing, merging
into journeys the app already has, and running twice without duplicating."""

from datetime import datetime

from backend.storage.events import list_events
from backend.storage.interviews import create_interview, list_interviews
from backend.storage.journeys import (
    create_journey,
    derive_status,
    find_journey,
    get_journey,
    update_journey,
)
from backend.tools.import_tracker_csv import (
    apply_plan,
    parse_date,
    parse_events,
    plan_row,
)

HEADERS = [
    "Title", "Company", "Location", "Status", "Submission", "Follow-up Message",
    "Recruiter Interview", "Screening Interview", "Hiring Manager Interview",
    "Technical Interview", "Leadership Interview", "Case Study",
    "Case Study Presentation", "On Hold", "Rejection", "Events", "Notes",
]


def sheet_row(**overrides) -> dict[str, str]:
    row = {h: "" for h in HEADERS}
    row.update(overrides)
    return row


def as_date(text: str) -> float:
    return datetime.strptime(text, "%d/%m/%Y").replace(hour=12).timestamp()


# --- parsing ----------------------------------------------------------------


def test_parses_european_dates():
    assert parse_date("09/07/2025") == as_date("09/07/2025")
    assert parse_date("09.07.2025") == as_date("09/07/2025")
    assert parse_date("2025-07-09") == as_date("09/07/2025")
    assert parse_date("") is None
    assert parse_date("sometime in July") is None


def test_parses_a_multiline_events_cell():
    dated, loose = parse_events(
        "16/07/2025 Video call with Clemence (VP Data)\n"
        "17/07/2025 Chat with Clemence\n"
        "recruiter never replied"
    )

    assert [text for _, text in dated] == [
        "Video call with Clemence (VP Data)",
        "Chat with Clemence",
    ]
    assert dated[0][0] == as_date("16/07/2025")
    # Undated prose is handed back, not dropped.
    assert loose == ["recruiter never replied"]


# --- mapping ----------------------------------------------------------------


async def test_maps_columns_onto_a_new_journey(test_db):
    row = sheet_row(
        Title="Head of Data", Company="BeReal", Location="Paris", Status="Rejected",
        Submission="18/08/2025", **{"Recruiter Interview": "28/08/2025"},
        **{"Case Study": "15/09/2025"}, Rejection="25/09/2025",
        Events="08/09/2025 Positive response from recruiter.",
        Notes="Case felt incomplete.",
    )

    plan = await plan_row(row, "p1")

    assert plan.action == "create"
    assert plan.status == "rejected"
    assert plan.fields["company_name"] == "BeReal"
    assert plan.fields["location"] == "Paris"
    assert plan.fields["applied_at"] == as_date("18/08/2025")
    assert plan.fields["rejected_at"] == as_date("25/09/2025")
    assert plan.fields["notes"] == "Case felt incomplete."
    assert [(slug, when) for slug, _, when in plan.rounds] == [
        ("recruiter", as_date("28/08/2025")),
        ("case_study", as_date("15/09/2025")),
    ]
    assert plan.events == [(as_date("08/09/2025"), "Positive response from recruiter.")]


async def test_status_column_is_discarded_when_dates_cover_it(test_db):
    """The sheet says Submitted; the dates say In Progress. Dates win."""
    row = sheet_row(
        Title="VP Data", Company="recap", Status="Submitted",
        Submission="16/07/2025", **{"Screening Interview": "22/08/2025"},
    )
    assert (await plan_row(row, "p1")).status == "in_progress"


async def test_follow_up_column_becomes_an_event(test_db):
    row = sheet_row(
        Title="Director of Data", Company="JustPlay", Submission="09/07/2025",
        **{"Follow-up Message": "28/07/2025"},
    )
    plan = await plan_row(row, "p1")

    assert plan.events == [(as_date("28/07/2025"), "Sent a follow-up message.")]
    # Applied in 2025 and never answered: the follow-up is one you sent, and a
    # follow-up is not a reply, so the row reads as gone quiet.
    assert plan.status == "silent"


async def test_dropped_status_without_a_date_column_is_anchored(test_db):
    """Nothing would regenerate Dropped otherwise — the row would read Applied."""
    row = sheet_row(
        Title="Head of Data", Company="Yepoda", Status="Dropped", Submission="15/07/2025"
    )

    plan = await plan_row(row, "p1")

    assert plan.status == "dropped"
    assert plan.fields["dropped_at"] == as_date("15/07/2025")
    assert plan.inferred and "dropped_at" in plan.inferred[0]


async def test_on_hold_status_anchors_to_the_latest_round(test_db):
    row = sheet_row(
        Title="Director AI", Company="Babbel", Status="on hold", Submission="14/07/2025",
        **{"Screening Interview": "05/08/2025"}, **{"Case Study": "21/08/2025"},
    )

    plan = await plan_row(row, "p1")

    assert plan.fields["on_hold_at"] == as_date("21/08/2025")
    assert plan.status == "on_hold"


async def test_row_without_title_or_company_is_skipped(test_db):
    plan = await plan_row(sheet_row(Notes="stray note"), "p1")
    assert plan.action == "skip"


async def test_undated_event_lines_are_folded_into_notes(test_db):
    row = sheet_row(
        Title="Head of Data", Company="GetAway", Submission="26/08/2025",
        Events="recruiter is Scott David", Notes="Berlin role.",
    )
    plan = await plan_row(row, "p1")

    assert plan.events == []
    assert "Berlin role." in plan.fields["notes"]
    assert "recruiter is Scott David" in plan.fields["notes"]


# --- writing ----------------------------------------------------------------


async def test_apply_creates_journey_rounds_and_events(test_db):
    row = sheet_row(
        Title="Head of Data", Company="BeReal", Submission="18/08/2025",
        **{"Recruiter Interview": "28/08/2025"}, Rejection="25/09/2025",
        Events="08/09/2025 Recruiter moved me forward.",
    )

    await apply_plan(await plan_row(row, "p1"), "p1")

    journey = await find_journey(
        profile_id="p1", job_url="", company_name="BeReal", job_title="Head of Data"
    )
    rounds = await list_interviews(journey["journey_id"])
    assert derive_status(journey, rounds) == "rejected"
    assert [r["interview_type"] for r in rounds] == ["recruiter"]
    assert rounds[0]["scheduled_at"] == as_date("28/08/2025")
    assert [e["text"] for e in await list_events(journey["journey_id"])] == [
        "Recruiter moved me forward."
    ]


async def test_merge_fills_gaps_without_overwriting(test_db):
    """The app already knows this job — the sheet only adds what is missing."""
    jid = await create_journey(
        profile_id="p1", company_name="Zenjob", job_title="Head of Data Science",
        cover_letter="Dear Zenjob", notes="Wrote this myself.",
    )
    await update_journey(jid, applied_at=as_date("15/07/2025"))

    row = sheet_row(
        Title="Head of Data Science", Company="Zenjob", Location="Berlin",
        Submission="22/07/2025", Rejection="04/08/2025", Notes="From the sheet.",
    )

    plan = await plan_row(row, "p1")
    assert plan.action == "merge"

    await apply_plan(plan, "p1")

    journey = await get_journey(jid)
    assert journey["cover_letter"] == "Dear Zenjob"
    assert journey["notes"] == "Wrote this myself."  # not clobbered
    assert journey["location"] == "Berlin"  # was empty, so filled
    assert journey["rejected_at"] == as_date("04/08/2025")
    assert journey["applied_at"] == as_date("15/07/2025")  # already set, kept


async def test_merges_on_company_when_the_title_differs(test_db):
    """The sheet is hand-typed, the app scrapes — titles rarely match exactly."""
    jid = await create_journey(
        profile_id="p1", company_name="Zenjob",
        job_title="Head of Analytics and Data Science (f/m/d)",
    )

    row = sheet_row(
        Title="Head of Data Science and Analytics", Company="Zenjob",
        Submission="22/07/2025", Rejection="04/08/2025",
    )
    plan = await plan_row(row, "p1")

    assert plan.action == "merge"
    assert plan.journey_id == jid
    assert "company alone" in plan.reason
    # The app's scraped title is the better one — the sheet's does not overwrite it.
    assert "job_title" not in plan.fields


async def test_ambiguous_company_creates_and_warns(test_db):
    await create_journey(profile_id="p1", company_name="Upvest", job_title="Director of Data")
    await create_journey(profile_id="p1", company_name="Upvest", job_title="Head of AI")

    plan = await plan_row(
        sheet_row(Title="Something Else", Company="Upvest", Submission="01/08/2025"), "p1"
    )

    assert plan.action == "create"
    assert plan.warnings and "several journeys" in plan.warnings[0]


async def test_exact_title_wins_over_ambiguity(test_db):
    await create_journey(profile_id="p1", company_name="Upvest", job_title="Director of Data")
    wanted = await create_journey(
        profile_id="p1", company_name="Upvest", job_title="Head of AI"
    )

    plan = await plan_row(
        sheet_row(Title="Head of AI", Company="Upvest", Submission="01/08/2025"), "p1"
    )

    assert plan.action == "merge"
    assert plan.journey_id == wanted
    assert not plan.warnings


async def test_importing_twice_changes_nothing(test_db):
    row = sheet_row(
        Title="Head of Data", Company="BeReal", Submission="18/08/2025",
        **{"Recruiter Interview": "28/08/2025"},
        Events="08/09/2025 Recruiter moved me forward.",
    )

    await apply_plan(await plan_row(row, "p1"), "p1")
    await apply_plan(await plan_row(row, "p1"), "p1")

    journey = await find_journey(
        profile_id="p1", job_url="", company_name="BeReal", job_title="Head of Data"
    )
    assert len(await list_interviews(journey["journey_id"])) == 1
    assert len(await list_events(journey["journey_id"])) == 1


async def test_import_is_scoped_to_one_profile(test_db):
    row = sheet_row(Title="Head of Data", Company="BeReal", Submission="18/08/2025")
    await apply_plan(await plan_row(row, "p1"), "p1")

    assert await find_journey(
        profile_id="p2", job_url="", company_name="BeReal", job_title="Head of Data"
    ) is None
