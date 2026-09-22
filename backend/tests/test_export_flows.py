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


def test_every_delivery_option_is_a_valid_state_value():
    """The node's answer has to survive the merge back into ApplicationState.

    `zip` and `links` were offered while the state still only accepted the
    pre-0.8.0 spellings, so choosing them killed the graph after the files had
    already been written.
    """
    for options in mod.DELIVERY_OPTIONS.values():
        for value, _label in options:
            ApplicationState(session_id="s", export_delivery=value)


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
    ApplicationState(session_id="s", **update)  # the merge LangGraph performs


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
    # Declining the files still leads to the tracker questions.
    assert update["phase"] == "log_application"


@pytest.mark.asyncio
async def test_typed_selection_is_accepted_alongside_the_ui_list(replies, written):
    state = _state("cover_letter", cover_letter="Dear team,", job_description="We hire")
    replies.extend(["cover_letter job_ad", "folder", "no"])

    await mod.export_node(state)

    assert [k for k, _ in written] == ["cover_letter", "job_ad"]


@pytest.mark.asyncio
async def test_export_node_never_interrupts_after_writing(replies, written):
    """The tracker and sheets questions live in their own nodes.

    An interrupt after the writes makes LangGraph replay the whole node on
    resume, producing a second copy of every file. Only two interrupts are
    scripted here — a third would pop from an empty list and raise.
    """
    state = _state("cover_letter", cover_letter="Dear team,")
    replies.extend([["cover_letter"], "folder"])

    update = await mod.export_node(state)

    assert [k for k, _ in written] == ["cover_letter"]
    assert update["phase"] == "log_application"


@pytest.mark.asyncio
async def test_sheets_node_appends_a_row_on_yes(replies, monkeypatch):
    appended: list[dict] = []
    monkeypatch.setattr(
        mod.exporters,
        "export_google_sheets",
        lambda state_dict: appended.append(state_dict) or "https://sheet",
    )
    state = _state("cover_letter", cover_letter="Dear team,")
    replies.append("yes")

    update = await mod.export_sheets_node(state)

    assert len(appended) == 1
    assert [r.kind for r in update["export_results"]][-1] == "sheets"
    assert update["phase"] == "post_export"


@pytest.mark.asyncio
async def test_sheets_node_skips_on_no(replies, monkeypatch):
    monkeypatch.setattr(
        mod.exporters,
        "export_google_sheets",
        lambda state_dict: pytest.fail("must not append when declined"),
    )
    state = _state("cover_letter", cover_letter="Dear team,")
    replies.append("no")

    assert await mod.export_sheets_node(state) == {"phase": "post_export"}


@pytest.mark.asyncio
async def test_other_assistants_go_straight_to_post_export(replies, written):
    state = _state("interview_prep", interview_briefing="# Briefing")
    replies.extend([["briefing"], "links"])

    update = await mod.export_node(state)

    assert update["phase"] == "post_export"


def test_cover_letter_tail_runs_export_then_tracker_then_sheets():
    """The order is the point: you need the letter in hand before you can say
    whether you sent it, and the sheet row is built from that answer."""
    from langgraph.checkpoint.memory import MemorySaver

    from backend.agent.graph import build_graph

    edges = {
        (e.source, e.target) for e in build_graph(MemorySaver()).get_graph().edges
    }
    assert ("qa_menu", "export") in edges
    assert ("export", "log_application") in edges
    assert ("log_application", "export_sheets") in edges
    assert ("export_sheets", "post_export") in edges


def _noop_update():
    async def _update(jid, **fields):
        return None

    return _update
