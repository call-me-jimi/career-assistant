"""Per-assistant export menus, delivery forms, and application-folder reuse."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent.nodes import export_node as mod
from backend.agent.state import ApplicationState


@pytest.fixture
def replies(monkeypatch):
    """Feed scripted answers to the node's successive interrupt() calls."""
    scripted: list[object] = []
    monkeypatch.setattr(mod, "emit_message", lambda *a, **k: None)
    monkeypatch.setattr(mod, "emit_export_ready", lambda *a, **k: None)
    monkeypatch.setattr(mod, "action_start", lambda *a, **k: "aid")
    monkeypatch.setattr(mod, "action_finish", lambda *a, **k: None)
    monkeypatch.setattr(mod, "interrupt", lambda payload: scripted.pop(0))
    return scripted


@pytest.fixture
def written(monkeypatch, tmp_path):
    """Record every write; each item lands in a distinct file."""
    calls: list[tuple[str, Path | None]] = []

    async def fake_write(key, state_dict, session_id, target):
        calls.append((key, target))
        folder = Path(target) if target else tmp_path / "fresh_folder"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{key}.out"
        path.write_text(key)
        return str(path)

    monkeypatch.setattr(mod, "_write_item", fake_write)
    return calls


def _state(assistant_type: str, **kw) -> ApplicationState:
    return ApplicationState(session_id="s", assistant_type=assistant_type, **kw)


@pytest.mark.asyncio
async def test_cover_letter_menu_hides_unavailable_items(replies, written):
    # No screenshot and no job description → those two items must not be offered.
    state = _state("cover_letter", cover_letter="Dear team,")
    replies.extend([["cover_letter", "application"], "folder", "no"])

    update = await mod.export_node(state)

    offered = [i.key for i in mod.EXPORT_ITEMS["cover_letter"] if i.available(state)]
    assert offered == ["cover_letter", "application", "traces"]
    assert [k for k, _ in written] == ["cover_letter", "application"]
    assert update["export_delivery"] == "folder"


def test_evaluator_offers_the_transcript_as_its_own_item():
    # The transcript costs a full re-transcription to recreate, so it must stay
    # visible in the picker whenever the session has one.
    state = _state(
        "interview_evaluator",
        interview_evaluation={"overall_score": 7},
        interview_transcript=[{"start": 0.0, "text": "hi"}],
    )
    offered = [i.key for i in mod.EXPORT_ITEMS["interview_evaluator"] if i.available(state)]
    assert offered == ["evaluation", "transcript", "traces"]

    # …and is hidden when there is nothing to write.
    bare = _state("interview_evaluator", interview_evaluation={"overall_score": 7})
    assert "transcript" not in [
        i.key for i in mod.EXPORT_ITEMS["interview_evaluator"] if i.available(bare)
    ]


@pytest.mark.asyncio
async def test_career_advisor_skips_the_delivery_question(replies, written):
    # Only one delivery form exists, so the node must not ask — a second
    # interrupt here would pop from an empty list and raise.
    state = _state("career_advisor", advisor_swot="## Strengths")
    replies.append(["swot"])

    update = await mod.export_node(state)

    assert update["export_delivery"] == "links"
    assert [k for k, _ in written] == ["swot"]


@pytest.mark.asyncio
async def test_zip_bundles_written_files(replies, written, monkeypatch, tmp_path):
    zipped: dict = {}

    def fake_zip(state_dict, paths, target_dir):
        zipped["paths"] = list(paths)
        archive = tmp_path / "bundle.zip"
        archive.write_text("zip")
        return str(archive)

    monkeypatch.setattr(mod.exporters, "export_zip", fake_zip)
    state = _state(
        "interview_evaluator",
        interview_evaluation={"overall_score": 7},
        interview_transcript=[{"start": 0.0, "text": "hi"}],
    )
    replies.extend([["evaluation", "transcript"], "zip"])

    update = await mod.export_node(state)

    assert len(zipped["paths"]) == 2
    assert [r.kind for r in update["export_results"]][-1] == "zip"


@pytest.mark.asyncio
async def test_evaluator_reuses_the_journeys_stored_folder(
    replies, written, monkeypatch, tmp_path
):
    original = tmp_path / "Statista - 2026.08.13"
    original.mkdir()

    async def fake_get_journey(jid):
        return {"export_folder": str(original)}

    monkeypatch.setattr(mod, "get_journey", fake_get_journey)
    monkeypatch.setattr(mod, "update_journey", _noop_update())

    state = _state(
        "interview_evaluator",
        journey_id="j1",
        interview_evaluation={"overall_score": 7},
    )
    replies.extend([["evaluation"], "folder"])

    await mod.export_node(state)

    assert written == [("evaluation", original)]


@pytest.mark.asyncio
async def test_missing_stored_folder_falls_back_to_a_fresh_one(
    replies, written, monkeypatch, tmp_path
):
    async def fake_get_journey(jid):
        return {"export_folder": str(tmp_path / "deleted-by-the-user")}

    monkeypatch.setattr(mod, "get_journey", fake_get_journey)
    monkeypatch.setattr(mod, "update_journey", _noop_update())

    state = _state("interview_prep", journey_id="j1", interview_briefing="# Briefing")
    replies.extend([["briefing"], "folder"])

    await mod.export_node(state)

    # target None → the exporter creates today's application folder.
    assert written == [("briefing", None)]


@pytest.mark.asyncio
async def test_folder_delivery_persists_the_folder_on_the_journey(
    replies, written, monkeypatch
):
    saved: dict = {}

    async def fake_update(jid, **fields):
        saved.update({"journey_id": jid, **fields})

    async def fake_get_journey(jid):
        return {}

    monkeypatch.setattr(mod, "get_journey", fake_get_journey)
    monkeypatch.setattr(mod, "update_journey", fake_update)

    state = _state("interview_prep", journey_id="j9", interview_briefing="# B")
    replies.extend([["briefing"], "folder"])

    await mod.export_node(state)

    assert saved["journey_id"] == "j9"
    assert saved["export_folder"].endswith("fresh_folder")


@pytest.mark.asyncio
async def test_none_skips_everything(replies, written):
    state = _state("cover_letter", cover_letter="Dear team,")
    replies.append("none")

    update = await mod.export_node(state)

    assert written == []
    assert update["phase"] == "post_export"


@pytest.mark.asyncio
async def test_typed_selection_is_accepted_alongside_the_ui_list(replies, written):
    state = _state("cover_letter", cover_letter="Dear team,", job_description="We hire")
    replies.extend(["cover_letter job_ad", "folder", "no"])

    await mod.export_node(state)

    assert [k for k, _ in written] == ["cover_letter", "job_ad"]


@pytest.mark.asyncio
async def test_sheets_only_offered_for_cover_letter(replies, written, monkeypatch):
    appended: list[str] = []
    monkeypatch.setattr(
        mod.exporters,
        "export_google_sheets",
        lambda state_dict: appended.append("row") or "https://sheet",
    )
    state = _state("cover_letter", cover_letter="Dear team,")
    replies.extend([["cover_letter"], "folder", "yes"])

    update = await mod.export_node(state)

    assert appended == ["row"]
    assert [r.kind for r in update["export_results"]][-1] == "sheets"


def _noop_update():
    async def _update(jid, **fields):
        return None

    return _update
