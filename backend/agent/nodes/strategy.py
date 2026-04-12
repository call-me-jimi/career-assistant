"""Strategy node: alignment (direct) or infer_role + position_candidate (recruiter)."""

from __future__ import annotations

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm


async def strategy_node(state: ApplicationState) -> dict:
    sid = state.session_id

    if state.job_source_type == "recruiter":
        # Step 1: infer_role
        aid = action_start(sid, "infer_role", "Inferring the real role from the recruiter ad")
        system = load_system_prompt("infer_role")
        user = render_user_prompt("infer_role", job_description=state.job_description)
        role_result = await call_llm(
            task="infer_role", system=system, user=user, session_id=sid
        )
        action_finish(sid, aid)

        # Step 2: position_candidate
        aid = action_start(sid, "position_candidate", "Building positioning strategy")
        system = load_system_prompt("position_candidate")
        user = render_user_prompt(
            "position_candidate",
            candidate_profile=state.candidate_profile,
            inferred_role_context=role_result.text,
            job_description=state.job_description,
        )
        pos_result = await call_llm(
            task="position_candidate", system=system, user=user, session_id=sid
        )
        action_finish(sid, aid)
        emit_message(sid, "Strategy prepared — now drafting your cover letter.")
        return {
            "inferred_role_context": role_result.text,
            "positioning_strategy": pos_result.text,
            "phase": "cl_loop",
        }

    # direct
    aid = action_start(sid, "alignment_strategy", "Building alignment strategy")
    system = load_system_prompt("generate_alignment_strategy")
    user = render_user_prompt(
        "generate_alignment_strategy",
        candidate_profile=state.candidate_profile,
        job_profile=state.job_description,
    )
    result = await call_llm(
        task="alignment_strategy", system=system, user=user, session_id=sid
    )
    action_finish(sid, aid)
    emit_message(sid, "Strategy prepared — now drafting your cover letter.")
    return {"alignment_strategy": result.text, "phase": "cl_loop"}
