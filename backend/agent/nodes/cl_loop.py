"""Cover letter generation + hiring-manager feedback loop.

Runs up to `max_hm_iterations` generate→simulate cycles. Stops early when
the HM score hits `quality_threshold`.
"""

from __future__ import annotations

import uuid

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState, CoverLetterVersion
from backend.config import load_settings
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm, parse_hm_feedback
from backend.storage.playbook import get_playbook, render_playbook_for_prompt


def _cl_prompt_stem(source: str) -> str:
    return "generate_cover_letter.recruiter" if source == "recruiter" else "generate_cover_letter"


def _cl_system_stem(source: str) -> str:
    return "cover_letter_generation_recruiter" if source == "recruiter" else "cover_letter_generation"


async def cl_loop_node(state: ApplicationState) -> dict:
    sid = state.session_id
    settings = load_settings()
    max_iters = settings.max_hm_iterations
    threshold = settings.quality_threshold

    emit_message(
        sid,
        f"I'll draft your cover letter and refine it up to {max_iters} times, aiming for a quality score of {threshold}/10 or higher.",
    )

    versions: list[CoverLetterVersion] = list(state.cover_letter_versions)
    feedback_notes = ""

    profile_playbook_text = ""
    if settings.learning_enabled and state.profile_id:
        playbook = await get_playbook(state.profile_id)
        profile_playbook_text = render_playbook_for_prompt(playbook)

    for iteration in range(1, max_iters + 1):
        # Generate
        aid = action_start(
            sid,
            "generate_cover_letter",
            f"Drafting cover letter (iteration {iteration}/{max_iters})",
        )
        cl_system = load_system_prompt(_cl_system_stem(state.job_source_type or "direct"))
        cl_user = render_user_prompt(
            _cl_prompt_stem(state.job_source_type or "direct"),
            applicant_name=state.applicant_name,
            job_title=state.job_title,
            company_name=state.company_name,
            job_description=state.job_description,
            company_description=state.company_description,
            candidate_profile=state.candidate_profile,
            alignment_strategy=state.alignment_strategy,
            positioning_strategy=state.positioning_strategy,
            inferred_role_context=state.inferred_role_context,
            cv_content=state.cv_text,
            hiring_manager_feedback=feedback_notes,
            profile_playbook=profile_playbook_text,
        )
        gen = await call_llm(
            task="cover_letter_generation",
            system=cl_system,
            user=cl_user,
            session_id=sid,
        )
        action_finish(sid, aid)
        version = CoverLetterVersion(
            version_id=str(uuid.uuid4()),
            text=gen.text,
            iteration=iteration,
        )

        # Simulate hiring manager
        aid = action_start(
            sid, "simulate_hiring_manager", f"Hiring manager review (iteration {iteration})"
        )
        hm_system = load_system_prompt("simulate_hiring_manager")
        hm_user = render_user_prompt(
            "simulate_hiring_manager",
            cv_content=state.cv_text,
            job_description=state.job_description,
            company_description=state.company_description,
            cover_letter=gen.text,
        )
        hm = await call_llm(
            task="simulate_hiring_manager",
            system=hm_system,
            user=hm_user,
            session_id=sid,
        )
        action_finish(sid, aid)

        try:
            feedback = parse_hm_feedback(hm.text)
        except Exception:
            feedback = None

        if feedback:
            version.hm_score = feedback.overall_score
            version.hm_feedback = feedback.model_dump()
            emit_message(
                sid,
                f"Draft {iteration}: hiring manager scored it **{feedback.overall_score:.1f}/10**.",
            )
            feedback_notes = (
                f"Previous score: {feedback.overall_score}/10.\n"
                f"Strengths: {'; '.join(feedback.strengths)}\n"
                f"Weaknesses: {'; '.join(feedback.weaknesses)}\n"
                f"Suggestions: {'; '.join(feedback.suggestions)}\n"
            )
            versions.append(version)
            if feedback.overall_score >= threshold:
                emit_message(sid, "Reached the quality target — finalising.")
                break
        else:
            emit_message(
                sid, f"Draft {iteration}: couldn't parse the feedback — keeping this version."
            )
            versions.append(version)

    # Choose best by score; fall back to last
    best = max(
        (v for v in versions if v.hm_score is not None),
        key=lambda v: v.hm_score or 0.0,
        default=versions[-1] if versions else None,
    )

    update: dict = {
        "cover_letter_versions": versions,
        "hm_iterations": len(versions),
        "phase": "cl_review",
    }
    if best:
        update["best_version_id"] = best.version_id
        update["cover_letter"] = best.text

    return update
