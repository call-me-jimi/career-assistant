"""Q&A phase: offer predefined questions + free-form, loop until user says done."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState, QAItem
from backend.llm.prompts import load_system_prompt
from backend.llm.service import call_llm
from backend.tools.web_search import tavily_search

PREDEFINED = {
    "motivation": "Briefly, why are you motivated to apply for this role at this company?",
    "salary": "What is your salary expectation for this role, and why?",
    "experience": "Which parts of your experience are most relevant to this role?",
}


async def qa_menu_node(state: ApplicationState) -> dict:
    sid = state.session_id
    if state.qa_items:
        prompt = (
            "Any other questions? Pick another topic, ask something custom, "
            "or reply `done` to move on."
        )
    else:
        prompt = (
            "Would you like me to help with any application questions?\n\n"
            "Choose a topic — `motivation`, `salary`, `experience` — or ask anything else. "
            "Reply `done` to skip to export."
        )
    emit_message(sid, prompt, key=f"qa_menu:prompt:{len(state.qa_items)}")
    reply = interrupt({"kind": "qa_menu"})
    text = (reply or "").strip() if isinstance(reply, str) else ""
    if not text or text.lower() == "done":
        return {"phase": "export"}

    kind = text.lower() if text.lower() in PREDEFINED else "custom"
    question = PREDEFINED.get(kind, text)
    return {
        "phase": "qa_answer",
        "qa_items": state.qa_items + [QAItem(kind=kind, question=question, answer="")],
    }


def _context_block(state: ApplicationState) -> str:
    return (
        f"Job title: {state.job_title}\n"
        f"Company: {state.company_name}\n"
        f"Job description: {state.job_description[:2000]}\n\n"
        f"Candidate profile: {state.candidate_profile[:2000]}\n"
    )


async def qa_answer_node(state: ApplicationState) -> dict:
    sid = state.session_id
    pending = [i for i, q in enumerate(state.qa_items) if not q.answer]
    if not pending:
        return {"phase": "qa_menu"}
    idx = pending[0]
    item = state.qa_items[idx]

    extra = ""
    if item.kind == "salary":
        aid = action_start(sid, "salary_search", "Looking up salary benchmarks")
        query = f"salary {state.job_title} {state.location or ''} {state.company_name}"
        results = tavily_search(query, max_results=4)
        action_finish(sid, aid)
        if results:
            extra = "\n\nMarket data:\n" + "\n".join(
                f"- {r.get('title', '')}: {r.get('content', '')[:200]}" for r in results
            )

    aid = action_start(sid, "qa_answer", f"Answering: {item.question[:60]}")
    system = load_system_prompt("qa")
    user = (
        f"Question: {item.question}\n\n"
        f"Context:\n{_context_block(state)}\n"
        f"Cover letter:\n{state.cover_letter[:2000]}{extra}\n\n"
        "Write a concise, authentic answer in first person."
    )
    result = await call_llm(task="qa", system=system, user=user, session_id=sid)
    action_finish(sid, aid)

    emit_message(sid, f"**{item.question}**")
    emit_message(sid, result.text)

    new_items = list(state.qa_items)
    new_items[idx] = QAItem(kind=item.kind, question=item.question, answer=result.text)
    return {"qa_items": new_items, "phase": "qa_menu"}
