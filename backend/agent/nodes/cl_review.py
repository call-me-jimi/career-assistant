"""Show the best cover letter to the user, allow one refinement loop."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState, CoverLetterVersion
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm


async def cl_review_node(state: ApplicationState) -> dict:
    sid = state.session_id

    details_url = f"/session/details?id={sid}"
    emit_message(
        sid,
        state.cover_letter or "(no cover letter produced)",
        key="cl_review:body",
    )
    emit_message(
        sid,
        "Here's the best version. You can also compare all drafts on the "
        f"[Details page]({details_url}).\n\n"
        "Reply `accept` to keep it, or describe any revisions you'd like.",
        key="cl_review:prompt",
    )
    reply = interrupt({"kind": "cl_review", "cover_letter": state.cover_letter})

    text = (reply or "").strip() if isinstance(reply, str) else ""
    if not text or text.lower() in {"accept", "ok", "looks good", "yes"}:
        return {"phase": "qa_menu"}

    # Single refinement pass using the chat system prompt
    aid = action_start(sid, "refine_cover_letter", "Applying your revisions")
    system = load_system_prompt("chat")
    user = (
        f"Here is the current cover letter:\n\n{state.cover_letter}\n\n"
        f"Please revise it based on this feedback: {text}\n\n"
        "Return only the revised cover letter."
    )
    result = await call_llm(
        task="refine_cover_letter", system=system, user=user, session_id=sid
    )
    action_finish(sid, aid)

    import uuid

    new_version = CoverLetterVersion(
        version_id=str(uuid.uuid4()),
        text=result.text,
        iteration=state.hm_iterations + 1,
    )
    emit_message(sid, "Revised version:")
    emit_message(sid, result.text)
    return {
        "cover_letter": result.text,
        "cover_letter_versions": state.cover_letter_versions + [new_version],
        "best_version_id": new_version.version_id,
        "phase": "qa_menu",
    }
