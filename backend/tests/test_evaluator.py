"""Smoke tests for the interview evaluator surface area."""

from __future__ import annotations

from backend.agent.state import ApplicationState
from backend.config import TranscriptionConfig
from backend.llm.schemas import InterviewEvaluation
from backend.llm.service import extract_json
from backend.tools.exporters import _render_evaluation_markdown
from backend.tools.transcribe import FasterWhisperProvider, build_provider

_RAW_EVAL = """
{
  "overall_score": 7.5,
  "decision": "MAYBE",
  "summary": "Solid technical answers, weak on storytelling.",
  "strengths": ["clear system design walkthrough"],
  "weaknesses": ["no STAR structure"],
  "improvements": ["lead with outcome"],
  "communication": {
    "pace": "appropriate",
    "filler_words": ["um", "like"],
    "clarity": "mostly clear",
    "structure": "inconsistent"
  },
  "per_question": [
    {
      "question": "tell me about yourself",
      "answer_summary": "meandered",
      "strengths": [],
      "weaknesses": ["no hook"],
      "suggested_improvement": "open with current role + key win"
    }
  ]
}
"""


def test_interview_evaluation_roundtrip_via_extract_json():
    data = extract_json(_RAW_EVAL)
    ev = InterviewEvaluation.model_validate(data)
    assert ev.decision == "MAYBE"
    assert ev.overall_score == 7.5
    assert ev.communication.pace == "appropriate"
    assert len(ev.per_question) == 1


def test_interview_evaluation_handles_code_fence():
    wrapped = "Here is the report:\n```json\n" + _RAW_EVAL + "\n```\n"
    data = extract_json(wrapped)
    ev = InterviewEvaluation.model_validate(data)
    assert ev.decision == "MAYBE"


def test_render_evaluation_markdown_smoke():
    data = extract_json(_RAW_EVAL)
    md = _render_evaluation_markdown(data)
    assert "Decision:** MAYBE" in md
    assert "Score:** 7.5/10" in md
    assert "tell me about yourself" in md
    assert "open with current role" in md


def test_state_has_evaluator_fields():
    s = ApplicationState(session_id="x", assistant_type="interview_evaluator")
    assert s.interview_evaluation is None
    assert s.interview_transcript == []
    assert s.interview_recording_duration_sec == 0.0


def test_build_provider_returns_faster_whisper():
    cfg = TranscriptionConfig()
    provider = build_provider(cfg)
    assert isinstance(provider, FasterWhisperProvider)
    assert provider.model_size == "turbo"
