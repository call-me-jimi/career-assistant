"""Step 10: transcription progress must publish safely from a worker thread.

FasterWhisperProvider.transcribe invokes on_progress from an asyncio.to_thread
worker thread; evaluator_transcribe_node marshals the emit back onto the event
loop via loop.call_soon_threadsafe. This exercises that cross-thread path and
asserts every progress event is delivered with no error.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from backend.agent.nodes import evaluator as ev
from backend.agent.state import ApplicationState


@pytest.mark.asyncio
async def test_progress_events_survive_cross_thread_publish(monkeypatch):
    progress: list[str] = []
    errors: list[str] = []

    def rec_emit(sid, text, *a, **k):
        if text.startswith("Transcribing…"):
            progress.append(text)

    class _Seg:
        def model_dump(self):
            return {"start": 0.0, "text": "hello"}

    class _Result:
        duration_sec = 120.0
        segments = [_Seg()]
        language = "en"

    class _Provider:
        async def transcribe(self, audio_path, on_progress=None, language=None):
            def work():
                for i in range(3):
                    try:
                        on_progress((i + 1) / 3, "snippet")  # called from a worker thread
                    except Exception as exc:  # pragma: no cover
                        errors.append(str(exc))
                return _Result()

            return await asyncio.to_thread(work)

    monkeypatch.setattr(ev, "emit_message", rec_emit)
    monkeypatch.setattr(ev, "get_cached_provider", lambda cfg: _Provider())

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name
    try:
        state = ApplicationState(
            session_id="tr-1",
            interview_recording_path=audio_path,
            interview_recording_filename="interview.wav",
        )
        update = await ev.evaluator_transcribe_node(state)
        for _ in range(5):  # flush call_soon_threadsafe callbacks
            await asyncio.sleep(0)
    finally:
        Path(audio_path).unlink(missing_ok=True)

    assert errors == []
    assert progress == ["Transcribing… 33%", "Transcribing… 66%", "Transcribing… 100%"]
    assert update["phase"] == "evaluator_analyze"
