"""The interview transcript must be exported whatever formats the user picks.

Re-transcribing costs the user a full pass over the recording and the export
prompt only comes round once, so the transcript is not one of the selectable
formats — it rides along automatically whenever the session has one.
"""
from __future__ import annotations

import pytest

from backend.agent.nodes import export_node as mod
from backend.agent.state import ApplicationState


@pytest.fixture
def _stub_export_node(monkeypatch, tmp_path):
    """Silence the event bus and make every exporter write a stub file."""
    monkeypatch.setattr(mod, "emit_message", lambda *a, **k: None)
    monkeypatch.setattr(mod, "emit_export_ready", lambda *a, **k: None)
    monkeypatch.setattr(mod, "action_start", lambda *a, **k: "aid")
    monkeypatch.setattr(mod, "action_finish", lambda *a, **k: None)
    monkeypatch.setattr(mod, "interrupt", lambda payload: "pdf")

    def _stub(name):
        def _write(state, target_dir=None):
            path = tmp_path / f"{name}.out"
            path.write_text(name)
            return str(path)

        return _write

    monkeypatch.setattr(mod.exporters, "export_pdf", _stub("pdf"))
    monkeypatch.setattr(mod.exporters, "export_transcript", _stub("transcript"))


@pytest.mark.asyncio
async def test_transcript_exported_even_when_user_only_asks_for_pdf(_stub_export_node):
    state = ApplicationState(
        session_id="s",
        assistant_type="interview_evaluator",
        export_delivery="download",  # skips the delivery interrupt
        interview_transcript=[{"start": 0.0, "text": "Thanks for joining."}],
    )

    update = await mod.export_node(state)

    kinds = [r.kind for r in update["export_results"]]
    assert kinds == ["pdf", "transcript"]


@pytest.mark.asyncio
async def test_no_transcript_export_when_session_has_none(_stub_export_node):
    state = ApplicationState(
        session_id="s",
        assistant_type="interview_evaluator",
        export_delivery="download",
    )

    update = await mod.export_node(state)

    assert [r.kind for r in update["export_results"]] == ["pdf"]
