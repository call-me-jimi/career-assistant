"""Interview evaluator nodes: context → upload → transcribe → analyze → review."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path

from langgraph.types import interrupt
from pydantic import ValidationError

from backend.agent.interrupts import (
    action_finish,
    action_start,
    emit_message,
    emit_state,
)
from backend.agent.state import ApplicationState
from backend.config import load_settings
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.schemas import InterviewEvaluation
from backend.llm.service import call_llm, extract_json
from backend.llm.translate import with_language_directive
from backend.storage.coaching_insights import save_coaching_insight
from backend.storage.feedback import (
    list_evaluator_calibration,
    render_calibration_for_prompt,
)
from backend.storage.interviews import describe_type, type_label, update_interview
from backend.storage.journeys import update_journey
from backend.tools.transcribe import get_cached_provider


async def evaluator_context_node(state: ApplicationState) -> dict:
    sid = state.session_id
    if state.interview_context:
        prompt = (
            "Here's what I already have about this round:\n\n"
            f"> {state.interview_context}\n\n"
            "Reply `none` to keep that, or describe the interview again to replace it."
        )
    else:
        round_name = type_label(state.interview_type) if state.interview_type else "interview"
        prompt = (
            f"Tell me anything you know about this {round_name.lower()} round — "
            "interviewers, focus areas, length, how it was run. Reply `none` if you'd "
            "rather just dive into the transcript."
        )
    emit_message(sid, prompt, key="evaluator_context:prompt")
    reply = interrupt({"kind": "evaluator_context"})
    text = (reply or "").strip() if isinstance(reply, str) else ""
    if text.lower() == "none":
        return {"interview_context": state.interview_context, "phase": "evaluator_upload"}
    if state.interview_id and text:
        try:
            await update_interview(state.interview_id, context=text)
        except Exception:
            pass  # context is a nice-to-have on the round record, never a blocker
    return {"interview_context": text, "phase": "evaluator_upload"}


async def evaluator_upload_node(state: ApplicationState) -> dict:
    sid = state.session_id
    emit_message(
        sid,
        "Upload the audio recording of your interview (m4a, mp3, wav, webm, ogg, "
        "flac, or mp4). Up to ~30–60 minutes works well. Need help recording on "
        "Ubuntu? Open the **How to record** guide next to the file picker.",
        key="evaluator_upload:prompt",
    )
    reply = interrupt({"kind": "upload_interview_audio"})

    if isinstance(reply, dict):
        audio_path = (reply.get("audio_path") or "").strip()
        filename = (reply.get("filename") or "").strip()
    else:
        audio_path = ""
        filename = ""

    if not audio_path or not Path(audio_path).exists():
        emit_message(sid, "No audio file received — let's try again.")
        return {"phase": "evaluator_upload"}

    return {
        "interview_recording_path": audio_path,
        "interview_recording_filename": filename or Path(audio_path).name,
        "phase": "evaluator_transcribe",
    }


async def evaluator_transcribe_node(state: ApplicationState) -> dict:
    sid = state.session_id
    audio_path = Path(state.interview_recording_path)
    if not audio_path.exists():
        emit_message(sid, f"⚠️ Recording file is gone: `{audio_path}`. Re-upload it.")
        return {"phase": "evaluator_upload"}

    aid = action_start(
        sid,
        "transcribe_interview",
        f"Transcribing {state.interview_recording_filename or audio_path.name} (this can take a few minutes)",
    )

    provider = get_cached_provider(load_settings().transcription)

    progress_seq = {"n": 0}
    loop = asyncio.get_running_loop()

    def on_progress(pct: float, snippet: str) -> None:
        progress_seq["n"] += 1
        loop.call_soon_threadsafe(
            partial(
                emit_message,
                sid,
                f"Transcribing… {int(pct * 100)}%",
                key=f"evaluator_transcribe:progress:{progress_seq['n']}",
            )
        )

    try:
        result = await provider.transcribe(audio_path, on_progress=on_progress)
    except Exception as exc:
        action_finish(sid, aid, status="error")
        emit_message(sid, f"⚠️ Transcription failed: `{exc}`")
        return {"phase": "evaluator_upload"}

    action_finish(sid, aid)
    emit_message(
        sid,
        f"Transcribed {result.duration_sec / 60:.1f} min of audio "
        f"({len(result.segments)} segments, language: `{result.language}`).",
        key="evaluator_transcribe:done",
    )

    return {
        "interview_transcript": [s.model_dump() for s in result.segments],
        "interview_transcript_language": result.language,
        "interview_recording_duration_sec": result.duration_sec,
        "phase": "evaluator_analyze",
    }


def _format_transcript(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start") or 0.0)
        mm, ss = divmod(int(start), 60)
        # Repeat the speaker on every line rather than only on change: the model
        # reads this out of order when citing evidence.
        speaker = (seg.get("speaker") or "").strip()
        prefix = f"{speaker}: " if speaker else ""
        lines.append(f"[{mm:02d}:{ss:02d}] {prefix}{text}")
    return "\n".join(lines)


async def _generate_evaluation(
    state: ApplicationState, *, revision_feedback: str = ""
) -> InterviewEvaluation:
    sid = state.session_id

    settings = load_settings()
    calibration = ""
    if settings.learning_enabled and state.profile_id:
        calibration = render_calibration_for_prompt(
            await list_evaluator_calibration(
                state.profile_id, limit=settings.calibration_window_n
            )
        )

    system = load_system_prompt("interview_evaluator")
    user = render_user_prompt(
        "analyze_interview_performance",
        calibration=calibration,
        company_name=state.company_name,
        job_title=state.job_title,
        job_description=state.job_description,
        candidate_profile=state.candidate_profile,
        interview_type=describe_type(state.interview_type, state.interview_label),
        interview_context=state.interview_context or "",
        interview_briefing=state.interview_briefing or "",
        transcript=_format_transcript(state.interview_transcript),
        revision_feedback=revision_feedback,
    )
    user = with_language_directive(user, state.language)
    result = await call_llm(
        task="analyze_interview_performance",
        system=system,
        user=user,
        session_id=sid,
    )
    data = extract_json(result.text)
    return InterviewEvaluation.model_validate(data)


async def evaluator_analyze_node(state: ApplicationState) -> dict:
    sid = state.session_id
    aid = action_start(sid, "analyze_interview_performance", "Generating your performance report")
    try:
        evaluation = await _generate_evaluation(state)
    except (ValidationError, json.JSONDecodeError) as exc:
        action_finish(sid, aid, status="error")
        emit_message(
            sid,
            f"⚠️ The model didn't return a valid report (`{exc}`). Try again with `retry`.",
        )
        return {"phase": "evaluator_review"}
    action_finish(sid, aid)

    evaluation_dict = evaluation.model_dump(mode="json")
    emit_state(sid, {"interview_evaluation": evaluation_dict})
    initial_version = {"iteration": 0, "evaluation": evaluation_dict}
    return {
        "interview_evaluation": evaluation_dict,
        "interview_evaluation_versions": [initial_version],
        "phase": "evaluator_review",
    }


async def evaluator_review_node(state: ApplicationState) -> dict:
    sid = state.session_id
    iteration = len(state.interview_evaluation_versions)
    has_report = bool(state.interview_evaluation)

    if has_report:
        prompt = (
            "Reply `accept` to move on to export, `retry` to regenerate from the same "
            "transcript, or describe specific revisions you'd like (e.g. "
            "\"be harsher on the prioritisation answer\", \"add more on storytelling\")."
        )
    else:
        prompt = (
            "No report was generated yet. Reply `retry` to try again from the same "
            "transcript, or describe what you'd like the report to focus on."
        )
    emit_message(sid, prompt, key=f"evaluator_review:prompt:{iteration}")
    reply = interrupt({"kind": "evaluator_review"})
    text = (reply or "").strip() if isinstance(reply, str) else ""
    lowered = text.lower()
    accepted = not text or lowered in {"accept", "ok", "looks good", "yes"}
    if accepted and not has_report:
        # Nothing to accept — force another generation pass instead of
        # exporting an empty report.
        emit_message(
            sid,
            "There's no report to accept yet — reply `retry` to generate one.",
        )
        return {"phase": "evaluator_review"}
    if accepted:
        if state.profile_id and state.interview_evaluation:
            try:
                await save_coaching_insight(
                    profile_id=state.profile_id,
                    session_id=state.session_id,
                    evaluation_dict=state.interview_evaluation,
                    job_title=state.job_title,
                    company_name=state.company_name,
                    journey_id=state.journey_id,
                    interview_id=state.interview_id,
                )
            except Exception:
                pass  # never block the accept flow
        if state.interview_evaluation and (state.journey_id or state.interview_id):
            ev = state.interview_evaluation
            summary = json.dumps(
                {"overall_score": ev.get("overall_score"), "summary": ev.get("summary", "")}
            )
            try:
                if state.journey_id:
                    await update_journey(state.journey_id, evaluation_summary=summary)
                if state.interview_id:
                    await update_interview(state.interview_id, evaluation_summary=summary)
            except Exception:
                pass
        return {"phase": "export"}

    aid = action_start(
        sid, "analyze_interview_performance", "Regenerating with your feedback"
    )
    try:
        revised = await _generate_evaluation(
            state, revision_feedback="" if lowered == "retry" else text
        )
    except (ValidationError, json.JSONDecodeError) as exc:
        action_finish(sid, aid, status="error")
        emit_message(sid, f"⚠️ Couldn't parse the revised report (`{exc}`). Try again.")
        return {"phase": "evaluator_review"}
    action_finish(sid, aid)

    revised_dict = revised.model_dump(mode="json")
    emit_state(sid, {"interview_evaluation": revised_dict})
    new_version = {"iteration": iteration, "evaluation": revised_dict}
    feedback_entry = {"iteration": iteration, "freetext": text}
    return {
        "interview_evaluation": revised_dict,
        "interview_evaluation_versions": state.interview_evaluation_versions
        + [new_version],
        "interview_evaluation_feedback": state.interview_evaluation_feedback
        + [feedback_entry],
        "phase": "evaluator_review",
    }
