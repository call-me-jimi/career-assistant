"""Local speech-to-text for interview recordings.

Single-pass transcription via faster-whisper. VAD-on, no pre-chunking
(the model handles arbitrarily long files via internal 30-sec windows
and a streaming segment generator).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field

from backend.config import TranscriptionConfig


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResult(BaseModel):
    language: str
    duration_sec: float
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""


ProgressCallback = Callable[[float, str], None]


class TranscriptionProvider(Protocol):
    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptionResult: ...


class FasterWhisperProvider:
    """faster-whisper-backed transcription. CPU- or GPU-capable."""

    def __init__(
        self,
        model_size: str = "turbo",
        device: str = "auto",
        compute_type: str = "auto",
        beam_size: int = 5,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def _run_sync(
        self,
        audio_path: Path,
        language: str | None,
        on_progress: ProgressCallback | None,
    ) -> TranscriptionResult:
        model = self._load_model()
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.beam_size,
            vad_filter=True,
            condition_on_previous_text=True,
        )

        collected: list[TranscriptSegment] = []
        full_parts: list[str] = []
        total = info.duration_after_vad or info.duration or 0.0
        last_report = 0.0
        for seg in segments_iter:
            text = (seg.text or "").strip()
            collected.append(TranscriptSegment(start=seg.start, end=seg.end, text=text))
            if text:
                full_parts.append(text)
            if on_progress and total > 0 and (seg.end - last_report) >= 10.0:
                pct = min(seg.end / total, 1.0)
                on_progress(pct, text)
                last_report = seg.end

        if on_progress and total > 0:
            on_progress(1.0, "")

        return TranscriptionResult(
            language=info.language,
            duration_sec=info.duration or 0.0,
            segments=collected,
            full_text="\n".join(full_parts),
        )

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        return await asyncio.to_thread(
            self._run_sync, audio_path, language, on_progress
        )


def build_provider(config: TranscriptionConfig) -> TranscriptionProvider:
    if config.provider == "faster_whisper":
        return FasterWhisperProvider(
            model_size=config.model,
            device=config.device,
            compute_type=config.compute_type,
            beam_size=config.beam_size,
        )
    raise ValueError(f"unknown transcription provider: {config.provider}")
