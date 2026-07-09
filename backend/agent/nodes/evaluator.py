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
from backend.storage.journeys import update_journey
from backend.tools.transcribe import get_cached_provider


async def evaluator_context_node(state: ApplicationState) -> dict:
    sid = state.session_id
    emit_message(
        sid,
        "Tell me anything you know about this interview round — format (screening, "
        "panel, technical, behavioural), interviewers, focus areas, length. Reply "
        "`none` if you'd rather just dive into the transcript.",
        key="evaluator_context:prompt",
    )
    reply = interrupt({"kind": "evaluator_context"})
    text = (reply or "").strip() if isinstance(reply, str) else ""
    if text.lower() == "none":
        text = ""
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
        lines.append(f"[{mm:02d}:{ss:02d}] {text}")
    return "\n".join(lines)


async def _generate_evaluation(
    state: ApplicationState, *, revision_feedback: str = ""
) -> InterviewEvaluation:
    sid = state.session_id
    system = load_system_prompt("interview_evaluator")
    user = render_user_prompt(
        "analyze_interview_performance",
        company_name=state.company_name,
        job_title=state.job_title,
        job_description=state.job_description,
        candidate_profile=state.candidate_profile,
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

    emit_message(
        sid,
        "Reply `accept` to move on to export, `retry` to regenerate from the same "
        "transcript, or describe specific revisions you'd like (e.g. "
        "\"be harsher on the prioritisation answer\", \"add more on storytelling\").",
        key=f"evaluator_review:prompt:{iteration}",
    )
    reply = interrupt({"kind": "evaluator_review"})
    text = (reply or "").strip() if isinstance(reply, str) else ""
    lowered = text.lower()
    if not text or lowered in {"accept", "ok", "looks good", "yes"}:
        if state.profile_id and state.interview_evaluation:
            try:
                await save_coaching_insight(
                    profile_id=state.profile_id,
                    session_id=state.session_id,
                    evaluation_dict=state.interview_evaluation,
                    job_title=state.job_title,
                    company_name=state.company_name,
                )
            except Exception:
                pass  # never block the accept flow
        if state.journey_id and state.interview_evaluation:
            try:
                ev = state.interview_evaluation
                await update_journey(
                    state.journey_id,
                    evaluation_summary=json.dumps(
                        {"overall_score": ev.get("overall_score"), "summary": ev.get("summary", "")}
                    ),
                )
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
