"""The employer_feedback_themes playbook category — distilled real employer feedback.

Kept apart from recurring_hm_weaknesses so the simulator's opinion and what companies
actually said never blur together.
"""

import aiosqlite
import pytest

from backend.storage.db import SCHEMA, _migrate
from backend.storage.playbook import (
    get_playbook,
    remove_playbook_item,
    render_playbook_for_prompt,
    upsert_playbook,
)


async def test_missing_playbook_has_an_empty_theme_list(test_db):
    assert (await get_playbook("nobody"))["employer_feedback_themes"] == []


async def test_themes_roundtrip(test_db):
    await upsert_playbook(
        "p1",
        {
            "employer_feedback_themes": [
                {"theme": "unclear industry motivation", "evidence": "said by 2 companies",
         "shared": False}
            ]
        },
    )

    themes = (await get_playbook("p1"))["employer_feedback_themes"]

    assert themes == [
        {"theme": "unclear industry motivation", "evidence": "said by 2 companies",
         "shared": False}
    ]


async def test_bare_strings_and_junk_are_normalised(test_db):
    await upsert_playbook(
        "p1",
        {"employer_feedback_themes": ["bare string", {"theme": ""}, 42, {"evidence": "orphan"}]},
    )

    assert (await get_playbook("p1"))["employer_feedback_themes"] == [
        {"theme": "bare string", "evidence": "", "shared": False}
    ]


async def test_themes_do_not_disturb_the_other_categories(test_db):
    await upsert_playbook(
        "p1",
        {
            "never_say": [{"phrase": "synergy"}],
            "recurring_hm_weaknesses": [{"weakness": "vague on scope"}],
            "employer_feedback_themes": [{"theme": "needs sharper ownership stories"}],
            "tone_notes": "direct",
        },
    )

    playbook = await get_playbook("p1")

    assert playbook["never_say"] == [{"phrase": "synergy", "reason": "", "shared": False}]
    assert playbook["recurring_hm_weaknesses"] == [
        {"weakness": "vague on scope", "shared": False}
    ]
    assert playbook["employer_feedback_themes"] == [
        {"theme": "needs sharper ownership stories", "evidence": "", "shared": False}
    ]
    assert playbook["tone_notes"] == "direct"


async def test_a_theme_can_be_removed(test_db):
    await upsert_playbook(
        "p1",
        {"employer_feedback_themes": [{"theme": "first"}, {"theme": "second"}]},
    )

    assert await remove_playbook_item("p1", "employer_feedback_themes", 0) is True

    assert (await get_playbook("p1"))["employer_feedback_themes"] == [
        {"theme": "second", "evidence": "", "shared": False}
    ]


async def test_migration_adds_the_column_to_a_pre_existing_database(tmp_path):
    path = tmp_path / "old.sqlite"
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await db.execute("DROP TABLE profile_playbook")
        await db.execute(
            """
            CREATE TABLE profile_playbook (
                profile_id               TEXT PRIMARY KEY,
                never_say                TEXT NOT NULL DEFAULT '[]',
                prefer_phrasing          TEXT NOT NULL DEFAULT '[]',
                recurring_hm_weaknesses  TEXT NOT NULL DEFAULT '[]',
                tone_notes               TEXT NOT NULL DEFAULT '',
                updated_at               REAL NOT NULL
            )
            """
        )
        await db.execute(
            "INSERT INTO profile_playbook (profile_id, updated_at) VALUES ('p1', 1.0)"
        )
        await db.commit()

    async with aiosqlite.connect(path) as db:
        await _migrate(db)
        await db.commit()
        cur = await db.execute("SELECT employer_feedback_themes FROM profile_playbook")
        existing = await cur.fetchone()

    assert existing == ("[]",)


# --- render_playbook_for_prompt -------------------------------------------


def test_render_is_empty_when_themes_are_the_only_absent_signal():
    assert render_playbook_for_prompt({"employer_feedback_themes": []}) == ""


def test_render_includes_themes_and_their_guardrail():
    rendered = render_playbook_for_prompt(
        {
            "employer_feedback_themes": [
                {"theme": "unclear industry motivation", "evidence": "2 companies"},
                {"theme": "wants sharper ownership stories"},
            ]
        }
    )

    assert "unclear industry motivation (2 companies)" in rendered
    assert "wants sharper ownership stories" in rendered
    assert "Never reference a past rejection" in rendered


def test_render_separates_real_feedback_from_the_simulator():
    rendered = render_playbook_for_prompt(
        {
            "recurring_hm_weaknesses": [{"weakness": "simulated concern"}],
            "employer_feedback_themes": [{"theme": "real concern"}],
        }
    )

    assert "Recurring hiring-manager concerns" in rendered
    assert "what real employers said" in rendered
    assert rendered.index("simulated concern") < rendered.index("real concern")


def test_render_tolerates_bare_string_themes():
    """Legacy or malformed rows must never crash rendering."""
    rendered = render_playbook_for_prompt({"employer_feedback_themes": ["bare theme"]})

    assert "bare theme" in rendered
