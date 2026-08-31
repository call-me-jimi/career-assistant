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


def test_extract_json_repairs_unescaped_inner_quotes():
    # LLMs frequently emit literal quotes inside long prose fields, which
    # breaks json.loads with "Expecting ',' delimiter". extract_json should
    # repair rather than raise.
    broken = (
        '{"overall_score": 7, "decision": "MAYBE", '
        '"summary": "You said "I led the migration" which landed well.", '
        '"strengths": [], "weaknesses": [], "improvements": []}'
    )
    data = extract_json(broken)
    assert data["overall_score"] == 7
    assert "led the migration" in data["summary"]


def test_render_evaluation_markdown_smoke():
    data = extract_json(_RAW_EVAL)
    md = _render_evaluation_markdown(data)
    assert "Decision:** MAYBE" in md
    assert "Score:** 7.5/10" in md
    assert "tell me about yourself" in md
    assert "open with current role" in md


def test_interviewer_insights_default_to_empty_for_older_reports():
    ev = InterviewEvaluation.model_validate(extract_json(_RAW_EVAL))
    assert ev.interviewer_insights == []


def test_interviewer_insights_parse_and_render():
    data = extract_json(_RAW_EVAL)
    data["interviewer_insights"] = [
        {"topic": "Team structure", "detail": "Six engineers, two squads, reports to the CTO."},
        {"topic": "Next steps", "detail": "Case study round within two weeks."},
    ]
    ev = InterviewEvaluation.model_validate(data)
    assert [i.topic for i in ev.interviewer_insights] == ["Team structure", "Next steps"]

    md = _render_evaluation_markdown(ev.model_dump(mode="json"))
    assert "What the interviewer told you" in md
    assert "**Team structure:** Six engineers" in md
    assert "Case study round" in md


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


def test_build_provider_passes_diarize_flag():
    assert build_provider(TranscriptionConfig(diarize=True)).diarize is True
    assert build_provider(TranscriptionConfig(diarize=False)).diarize is False


def test_format_transcript_labels_every_line_when_diarized():
    from backend.agent.nodes.evaluator import _format_transcript

    out = _format_transcript(
        [
            {"start": 0.0, "text": "Tell me about yourself.", "speaker": "SPEAKER_A"},
            {"start": 65.0, "text": "Sure.", "speaker": "SPEAKER_B"},
            {"start": 70.0, "text": "I lead data teams.", "speaker": "SPEAKER_B"},
        ]
    )
    assert out.splitlines() == [
        "[00:00] SPEAKER_A: Tell me about yourself.",
        "[01:05] SPEAKER_B: Sure.",
        "[01:10] SPEAKER_B: I lead data teams.",
    ]


def test_format_transcript_unchanged_without_speaker_labels():
    from backend.agent.nodes.evaluator import _format_transcript

    out = _format_transcript([{"start": 0.0, "text": "Tell me about yourself."}])
    assert out == "[00:00] Tell me about yourself."
