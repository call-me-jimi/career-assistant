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


def test_whisper_segment_is_split_at_pauses_between_words():
    from types import SimpleNamespace as W

    from backend.tools.transcribe import _split_on_pauses

    seg = W(
        start=5202.4,
        end=5216.6,
        text=" have a nice day you too bye",
        words=[
            W(start=5202.4, end=5202.9, word=" have"),
            W(start=5202.9, end=5203.0, word=" a"),
            W(start=5203.0, end=5203.3, word=" nice"),
            W(start=5203.3, end=5203.6, word=" day"),
            W(start=5204.2, end=5204.4, word=" you"),  # 0.6 s pause: turn change
            W(start=5204.4, end=5204.7, word=" too"),
            W(start=5206.8, end=5207.1, word=" bye"),
        ],
    )
    assert [(p.start, p.end, p.text) for p in _split_on_pauses(seg)] == [
        (5202.4, 5203.6, "have a nice day"),
        (5204.2, 5204.7, "you too"),
        (5206.8, 5207.1, "bye"),
    ]


def test_segment_without_word_timestamps_is_kept_whole():
    from types import SimpleNamespace as W

    from backend.tools.transcribe import _split_on_pauses

    (only,) = _split_on_pauses(W(start=0.0, end=4.0, text=" Hello there.", words=None))
    assert (only.start, only.end, only.text) == (0.0, 4.0, "Hello there.")


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


def _patch_context_node(monkeypatch, reply):
    from backend.agent.nodes import evaluator as ev

    messages: list[str] = []
    saved: list[tuple] = []

    async def fake_update(interview_id, **fields):
        saved.append((interview_id, fields))

    monkeypatch.setattr(ev, "emit_message", lambda sid, text, **kw: messages.append(text))
    monkeypatch.setattr(ev, "interrupt", lambda payload: reply)
    monkeypatch.setattr(ev, "update_interview", fake_update)
    return ev, messages, saved


async def test_context_noted_at_scheduling_is_shown_and_added_to(monkeypatch):
    ev, messages, saved = _patch_context_node(monkeypatch, "Ana brought her manager along")
    state = ApplicationState(
        session_id="s", interview_id="i1", interview_context="Live coding\n45 min"
    )

    update = await ev.evaluator_context_node(state)

    assert "> Live coding\n> 45 min" in messages[0]
    assert "Anything to add" in messages[0]
    assert update["interview_context"] == "Live coding\n45 min\n\nAna brought her manager along"
    assert saved == [("i1", {"context": update["interview_context"]})]


async def test_none_keeps_the_noted_context(monkeypatch):
    ev, _, saved = _patch_context_node(monkeypatch, "none")
    state = ApplicationState(session_id="s", interview_id="i1", interview_context="Live coding")

    update = await ev.evaluator_context_node(state)

    assert update["interview_context"] == "Live coding"
    assert not saved
