"""Show the best cover letter to the user, loop revisions until accepted."""

from __future__ import annotations

import uuid

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState, CoverLetterVersion
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm, parse_hm_feedback

_FEEDBACK_CATEGORIES = {"tone", "accuracy", "length", "specific_claim", "emphasis", "other"}


def _parse_category_prefix(text: str) -> tuple[str | None, str]:
    """Extract an optional leading `<category>:` tag from the revision text.

    Returns (category, remaining_text). Category is None when the prefix is
    missing or unrecognised; remaining_text is always safe to use verbatim.
    """
    stripped = text.lstrip()
    if ":" not in stripped:
        return None, text
    head, rest = stripped.split(":", 1)
    head_norm = head.strip().lower().replace(" ", "_").replace("-", "_")
    if head_norm in _FEEDBACK_CATEGORIES:
        return head_norm, rest.strip()
    return None, text


def _parse_rescore_prefix(text: str) -> tuple[bool, str]:
    """Detect a leading `rescore:` or `rescore ` flag (case-insensitive).

    Returns (rescore_requested, remaining_text). When the prefix is absent,
    the original text is returned unchanged.
    """
    stripped = text.lstrip()
    lowered = stripped.lower()
    if lowered == "rescore":
        return True, ""
    for prefix in ("rescore:", "rescore "):
        if lowered.startswith(prefix):
            return True, stripped[len(prefix):].lstrip()
    return False, text


async def cl_review_node(state: ApplicationState) -> dict:
    sid = state.session_id
    iteration = state.hm_iterations

    details_url = f"/session/details?id={sid}"
    emit_message(
        sid,
        state.cover_letter or "(no cover letter produced)",
        key=f"cl_review:body:{iteration}",
    )
    emit_message(
        sid,
        "Here's the current version. You can also compare all drafts on the "
        f"[Details page]({details_url}).\n\n"
        "Reply `accept` to keep it, or describe any revisions you'd like.\n\n"
        "_Tip: prefix with `rescore:` to also re-run the hiring-manager review on "
        "the revised version (e.g. `rescore: tone: more formal`). "
        "Use a category tag (`tone:`, `accuracy:`, `length:`, `specific_claim:`, "
        "`emphasis:`, `other:`) to help me learn your preferences. Both prefixes are optional._",
        key=f"cl_review:prompt:{iteration}",
    )
    reply = interrupt({"kind": "cl_review", "cover_letter": state.cover_letter})

    text = (reply or "").strip() if isinstance(reply, str) else ""
    if not text or text.lower() in {"accept", "ok", "looks good", "yes"}:
        return {"phase": "qa_menu"}

    rescore, remaining = _parse_rescore_prefix(text)
    category, freetext = _parse_category_prefix(remaining)
    revision_text = freetext or remaining or text

    aid = action_start(sid, "refine_cover_letter", "Applying your revisions")
    chat_system = load_system_prompt("chat")
    user = (
        f"Here is the current cover letter:\n\n{state.cover_letter}\n\n"
        f"Please revise it based on this feedback: {revision_text}\n\n"
        "Return only the revised cover letter."
    )
    result = await call_llm(
        task="refine_cover_letter", system=chat_system, user=user, session_id=sid
    )
    action_finish(sid, aid)

    new_version = CoverLetterVersion(
        version_id=str(uuid.uuid4()),
        text=result.text,
        iteration=iteration + 1,
    )

    if rescore:
        aid = action_start(
            sid, "simulate_hiring_manager", "Re-running hiring manager review"
        )
        hm_system = load_system_prompt("simulate_hiring_manager")
        hm_user = render_user_prompt(
            "simulate_hiring_manager",
            cv_content=state.cv_text,
            job_description=state.job_description,
            company_description=state.company_description,
            cover_letter=result.text,
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
            new_version.hm_score = feedback.overall_score
            new_version.hm_feedback = feedback.model_dump()
            emit_message(
                sid,
                f"Revised draft: hiring manager scored it **{feedback.overall_score:.1f}/10**.",
            )
        else:
            emit_message(sid, "Revised draft: couldn't parse the hiring-manager feedback.")

    feedback_entry = {
        "iteration": iteration,
        "category": category,
        "freetext": revision_text,
        "rescore_requested": rescore,
    }
    return {
        "cover_letter": result.text,
        "cover_letter_versions": state.cover_letter_versions + [new_version],
        "best_version_id": new_version.version_id,
        "hm_iterations": iteration + 1,
        "revision_feedback": state.revision_feedback + [feedback_entry],
        "phase": "cl_review",
    }
