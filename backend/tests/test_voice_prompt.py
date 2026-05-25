"""Smoke test for the voice-prompt transcription endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import uploads
from backend.tools.transcribe import TranscriptionResult


class _StubProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str | None]] = []

    async def transcribe(self, audio_path: Path, *, language=None, on_progress=None):
        self.calls.append((Path(audio_path), language))
        return TranscriptionResult(
            language=language or "en",
            duration_sec=1.23,
            segments=[],
            full_text="hello world",
        )


@pytest.fixture
def stub_provider(monkeypatch):
    provider = _StubProvider()
    monkeypatch.setattr(uploads, "get_cached_provider", lambda _cfg: provider)
    return provider


@pytest.fixture
def stub_session(monkeypatch):
    async def fake_get_session(session_id: str):
        return {"session_id": session_id, "language": "German"}

    monkeypatch.setattr(uploads, "get_session", fake_get_session)


def _app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(uploads.voice_router)
    return app


def test_voice_prompt_returns_text_and_cleans_up(stub_provider, stub_session):
    client = TestClient(_app())
    audio_bytes = b"fake-webm-payload"

    res = client.post(
        "/api/transcribe/voice-prompt",
        data={"session_id": "abc123"},
        files={"file": ("clip.webm", audio_bytes, "audio/webm")},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == "hello world"
    assert body["duration_sec"] == pytest.approx(1.23)

    assert len(stub_provider.calls) == 1
    written_path, language = stub_provider.calls[0]
    assert language == "de"  # German → de
    assert not written_path.exists(), "temp file should be deleted after transcription"


def test_voice_prompt_rejects_empty_payload(stub_provider, stub_session):
    client = TestClient(_app())
    res = client.post(
        "/api/transcribe/voice-prompt",
        data={"session_id": "abc123"},
        files={"file": ("clip.webm", b"", "audio/webm")},
    )
    assert res.status_code == 400
    assert stub_provider.calls == []


def test_voice_prompt_rejects_oversize(stub_provider, stub_session, monkeypatch):
    # Squeeze the cap down to 1 byte so a small payload trips it.
    from backend.api import uploads as uploads_mod
    from backend.config import AppSettings, TranscriptionConfig

    tiny = TranscriptionConfig(voice_max_mb=0)
    # voice_max_mb=0 means cap is 0 bytes → any non-empty payload exceeds
    monkeypatch.setattr(
        uploads_mod,
        "load_settings",
        lambda: AppSettings(transcription=tiny),
    )

    client = TestClient(_app())
    res = client.post(
        "/api/transcribe/voice-prompt",
        data={"session_id": "abc123"},
        files={"file": ("clip.webm", b"x" * 16, "audio/webm")},
    )
    assert res.status_code == 413
