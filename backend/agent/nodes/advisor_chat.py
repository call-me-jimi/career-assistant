"""Career advisor open-chat loop.

One invocation = one turn. The graph re-enters this node after each user
reply so the conversation can run indefinitely until the user types `done`
or `/swot`.
"""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState, ChatTurn
from backend.llm.prompts import load_system_prompt
from backend.llm.service import call_llm
from backend.llm.translate import with_language_directive


def _history_for_llm(transcript: list[ChatTurn]) -> list[dict]:
    return [{"role": t.role, "content": t.content} for t in transcript]


async def advisor_chat_node(state: ApplicationState) -> dict:
    sid = state.session_id
    transcript: list[ChatTurn] = list(state.advisor_transcript)

    if not transcript:
        opening = (
            "So — let's talk about your career. I've read your profile, but I'd rather hear it "
            "from you. Where would you like to start? A recent role that's on your mind, a "
            "decision you're wrestling with, or how you'd describe what you do today in one "
            "sentence?\n\n"
            "_Type `/swot` any time you'd like a written strengths/weaknesses summary, or "
            "`done` when you want to wrap up._"
        )
        emit_message(sid, opening, key="advisor_chat:opening")

    reply = interrupt({"kind": "advisor_chat"})
    text = (reply or "").strip() if isinstance(reply, str) else ""

    if not text:
        return {"phase": "advisor_chat"}

    lowered = text.lower()
    if lowered == "done":
        emit_message(sid, "Thanks for the conversation. Let's wrap up.")
        return {"phase": "export"}
    if lowered in {"/swot", "swot"}:
        return {"phase": "advisor_swot"}

    transcript.append(ChatTurn(role="user", content=text))

    aid = action_start(sid, "advisor_chat", "Thinking")
    system = load_system_prompt("career_advisor")
    system_with_profile = (
        f"{system}\n\n--- CANDIDATE PROFILE ---\n{state.candidate_profile}\n"
    )
    system_with_profile = with_language_directive(system_with_profile, state.language)
    history = _history_for_llm(transcript[:-1])
    result = await call_llm(
        task="career_advisor_chat",
        system=system_with_profile,
        user=text,
        session_id=sid,
        history=history,
    )
    action_finish(sid, aid)

    transcript.append(ChatTurn(role="assistant", content=result.text))
    emit_message(sid, result.text, localized=True)

    return {"advisor_transcript": transcript, "phase": "advisor_chat"}
