"""Learnings are profile-specific until promoted.

Nothing crosses CVs on its own: a lesson belongs to the profile that earned it.
Sharing makes it readable everywhere from the next generation onward — and is
one-way, because it cannot reach back into a playbook that has already absorbed it.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.routes import router
from backend.storage.playbook import (
    get_playbook,
    list_shared_items,
    merge_shared,
    render_playbook_for_prompt,
    set_item_shared,
    upsert_playbook,
)
from backend.storage.profiles import save_profile


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _profiles() -> None:
    for pid, name in (("data", "Head of Data"), ("ai", "Head of AI")):
        await save_profile(
            profile_id=pid, name=name, applicant_name="Hendrik", cv_text="…",
            candidate_profile="…",
        )


async def _learned(profile_id: str, theme: str, *, shared: bool = False) -> None:
    await upsert_playbook(
        profile_id,
        {"employer_feedback_themes": [{"theme": theme, "evidence": "voize", "shared": shared}]},
    )


# --- the flag survives a write ---------------------------------------------


async def test_items_are_unshared_by_default(test_db):
    await _learned("data", "wants a team built from zero")

    item = (await get_playbook("data"))["employer_feedback_themes"][0]
    assert item["shared"] is False


async def test_sharing_survives_the_normalisers(test_db):
    await _learned("data", "wants a team built from zero", shared=True)

    assert (await get_playbook("data"))["employer_feedback_themes"][0]["shared"] is True


async def test_set_item_shared_toggles_one_item(test_db):
    await _learned("data", "wants a team built from zero")

    assert await set_item_shared("data", "employer_feedback_themes", 0, True) is True
    assert (await get_playbook("data"))["employer_feedback_themes"][0]["shared"] is True

    await set_item_shared("data", "employer_feedback_themes", 0, False)
    assert (await get_playbook("data"))["employer_feedback_themes"][0]["shared"] is False


async def test_set_item_shared_rejects_nonsense(test_db):
    await _learned("data", "a theme")

    assert await set_item_shared("data", "not_a_category", 0, True) is False
    assert await set_item_shared("data", "employer_feedback_themes", 9, True) is False


# --- what another profile sees ---------------------------------------------


async def test_an_unshared_lesson_stays_where_it_was_learned(test_db):
    await _learned("data", "wants a team built from zero")

    assert await list_shared_items("ai") == {
        "never_say": [],
        "prefer_phrasing": [],
        "recurring_hm_weaknesses": [],
        "employer_feedback_themes": [],
    }


async def test_a_shared_lesson_reaches_every_other_profile(test_db):
    await _learned("data", "wants a team built from zero", shared=True)

    shared = await list_shared_items("ai")
    assert [t["theme"] for t in shared["employer_feedback_themes"]] == [
        "wants a team built from zero"
    ]
    # So the UI can say where it came from.
    assert shared["employer_feedback_themes"][0]["profile_id"] == "data"


async def test_a_profile_does_not_see_its_own_shared_items_twice(test_db):
    await _learned("data", "wants a team built from zero", shared=True)

    assert await list_shared_items("data") == {
        "never_say": [],
        "prefer_phrasing": [],
        "recurring_hm_weaknesses": [],
        "employer_feedback_themes": [],
    }


# --- what the prompt renders -----------------------------------------------


async def test_a_shared_lesson_is_rendered_into_another_profiles_prompt(test_db):
    await _learned("data", "wants a team built from zero", shared=True)

    text = render_playbook_for_prompt(
        await get_playbook("ai"), shared=await list_shared_items("ai")
    )

    assert "wants a team built from zero" in text


async def test_an_unshared_lesson_is_not(test_db):
    await _learned("data", "wants a team built from zero")

    text = render_playbook_for_prompt(
        await get_playbook("ai"), shared=await list_shared_items("ai")
    )

    assert text == ""


def test_own_wording_wins_over_a_shared_duplicate():
    own = {"employer_feedback_themes": [{"theme": "same lesson", "evidence": "mine"}]}
    shared = {"employer_feedback_themes": [{"theme": "same lesson", "evidence": "theirs"}]}

    merged = merge_shared(own, shared)

    assert merged["employer_feedback_themes"] == [{"theme": "same lesson", "evidence": "mine"}]


def test_rendering_without_shared_items_is_unchanged():
    own = {"employer_feedback_themes": [{"theme": "a lesson", "evidence": ""}]}

    assert render_playbook_for_prompt(own) == render_playbook_for_prompt(own, shared=None)


# --- the endpoint -----------------------------------------------------------


async def test_share_endpoint_promotes_an_item(client):
    await _profiles()
    await _learned("data", "wants a team built from zero")

    r = await client.post(
        "/api/profiles/data/playbook/employer_feedback_themes/0/share", json={"shared": True}
    )

    assert r.status_code == 200
    assert (await get_playbook("data"))["employer_feedback_themes"][0]["shared"] is True


async def test_playbook_endpoint_carries_what_others_shared(client):
    await _profiles()
    await _learned("data", "wants a team built from zero", shared=True)

    body = (await client.get("/api/profiles/ai/playbook")).json()

    assert [t["theme"] for t in body["shared"]["employer_feedback_themes"]] == [
        "wants a team built from zero"
    ]


async def test_share_endpoint_404s_on_a_missing_item(client):
    await _profiles()

    r = await client.post(
        "/api/profiles/data/playbook/employer_feedback_themes/0/share", json={"shared": True}
    )

    assert r.status_code == 404
