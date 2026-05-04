"""Coach extras after the interview briefing: menu + four sub-flows.

Mirrors the qa_menu / qa_answer pattern from the cover-letter graph: a menu
node with an interrupt loops back to itself (via a phase router in the graph)
until the user picks `done`, at which point we route to export.
"""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState, ChatTurn
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm

_MENU_OPTIONS = {"mock", "practice", "tech", "questions"}

_MOCK_STEER_NEXT = {"next", "different", "another", "skip", "more"}
_MOCK_STEER_END = {"done", "stop", "enough"}
_FEEDBACK_MARKER = "<!-- fb -->"


def _menu_seq(state: ApplicationState) -> int:
    """Stable sequence for menu re-entry, used as the emit_message key."""
    return len(state.interview_extras) + len(state.mock_interview_transcript)


async def interview_menu_node(state: ApplicationState) -> dict:
    sid = state.session_id
    seq = _menu_seq(state)
    if seq == 0:
        prompt = (
            "Briefing locked in. I can also help you prepare in other ways — pick one:\n\n"
            "- `mock` — open-ended mock interview (I ask, you answer, I give feedback)\n"
            "- `practice` — sample answers to the classic questions (\"tell me about yourself\", etc.)\n"
            "- `tech` — focused refresher on a technical / domain topic\n"
            "- `questions` — questions you can ask the interviewer\n\n"
            "Or reply `done` to skip to export."
        )
    else:
        prompt = (
            "Anything else? Pick `mock`, `practice`, `tech`, `questions`, or `done` to export."
        )
    emit_message(sid, prompt, key=f"interview_menu:prompt:{seq}")
    reply = interrupt({"kind": "interview_menu"})
    text = (reply or "").strip().lower() if isinstance(reply, str) else ""

    if text not in _MENU_OPTIONS:
        return {"phase": "export"}

    phase_map = {
        "mock": "interview_mock",
        "practice": "interview_practice",
        "tech": "interview_tech",
        "questions": "interview_questions",
    }
    return {"phase": phase_map[text]}


def _format_transcript(turns: list[ChatTurn]) -> str:
    if not turns:
        return "(no prior turns)"

    def _label(t: ChatTurn) -> str:
        if t.role == "assistant" and t.content.startswith(_FEEDBACK_MARKER):
            return "COACH"
        return "INTERVIEWER" if t.role == "assistant" else "CANDIDATE"

    def _content(t: ChatTurn) -> str:
        if t.content.startswith(_FEEDBACK_MARKER):
            return t.content[len(_FEEDBACK_MARKER):].lstrip()
        return t.content

    return "\n\n".join(f"{_label(t)}: {_content(t)}" for t in turns[-8:])


def _last_user_text(turns: list[ChatTurn]) -> str:
    for t in reversed(turns):
        if t.role == "user":
            return t.content.strip().lower()
    return ""


def _last_question(turns: list[ChatTurn]) -> str:
    """Find the most recent assistant turn that's a question, not feedback."""
    for t in reversed(turns):
        if t.role == "assistant" and not t.content.startswith(_FEEDBACK_MARKER):
            return t.content
    return ""


async def mock_interview_node(state: ApplicationState) -> dict:
    """Open-ended mock interview loop.

    Each pass generates either a new question (when the transcript is empty
    or the last user reply was a steering keyword like `next`) or feedback
    on the candidate's most recent answer. Exits to the menu on `done`.
    """
    sid = state.session_id
    turns = list(state.mock_interview_transcript)
    seq = len(turns)
    last_user = _last_user_text(turns)
    needs_question = (not turns) or (last_user in _MOCK_STEER_NEXT)

    if needs_question:
        aid = action_start(sid, "mock_interview_question", "Picking your next question")
        user_prompt = render_user_prompt(
            "mock_interview_question",
            company_name=state.company_name,
            job_title=state.job_title,
            job_description=state.job_description[:3000],
            interview_context=state.interview_context or "",
            candidate_profile=state.candidate_profile[:2500],
            alignment_strategy=state.alignment_strategy or state.inferred_role_context or "",
            transcript=_format_transcript(turns),
            user_request=last_user,
        )
        result = await call_llm(
            task="mock_interview_question",
            system=load_system_prompt("chat"),
            user=user_prompt,
            session_id=sid,
        )
        action_finish(sid, aid)

        emit_message(sid, f"**Q{seq + 1}.** {result.text}", key=f"mock:q:{seq}")
        emit_message(
            sid,
            "_Reply with your answer — or `next` to skip, `different` to switch topic, "
            "`done` to stop._",
            key=f"mock:hint:{seq}",
        )
        question_turn = ChatTurn(role="assistant", content=result.text)
        reply = interrupt({"kind": "mock_interview"})
        text = (reply or "").strip() if isinstance(reply, str) else ""
        if text.lower() in _MOCK_STEER_END:
            return {
                "mock_interview_transcript": turns + [question_turn],
                "phase": "interview_menu",
            }
        return {
            "mock_interview_transcript": turns
            + [question_turn, ChatTurn(role="user", content=text)],
            "phase": "interview_mock",
        }

    answer_text = turns[-1].content
    question_text = _last_question(turns)

    aid = action_start(sid, "mock_interview_feedback", "Reviewing your answer")
    feedback_prompt = render_user_prompt(
        "mock_interview_feedback",
        question=question_text,
        answer=answer_text,
        job_title=state.job_title,
        company_name=state.company_name,
        job_description=state.job_description[:2500],
        candidate_profile=state.candidate_profile[:2500],
    )
    result = await call_llm(
        task="mock_interview_feedback",
        system=load_system_prompt("chat"),
        user=feedback_prompt,
        session_id=sid,
    )
    action_finish(sid, aid)

    emit_message(sid, result.text, key=f"mock:fb:{seq}")
    emit_message(
        sid,
        "_Reply with another answer (to dig deeper), `next` for a new question, or `done` to stop._",
        key=f"mock:fb-hint:{seq}",
    )
    feedback_turn = ChatTurn(
        role="assistant", content=f"{_FEEDBACK_MARKER}\n{result.text}"
    )
    reply = interrupt({"kind": "mock_interview"})
    text = (reply or "").strip() if isinstance(reply, str) else ""
    if text.lower() in _MOCK_STEER_END:
        return {
            "mock_interview_transcript": turns + [feedback_turn],
            "phase": "interview_menu",
        }
    return {
        "mock_interview_transcript": turns
        + [feedback_turn, ChatTurn(role="user", content=text)],
        "phase": "interview_mock",
    }


async def interview_practice_node(state: ApplicationState) -> dict:
    sid = state.session_id
    aid = action_start(sid, "interview_practice", "Drafting common-question answers")
    system = load_system_prompt("chat")
    user = render_user_prompt(
        "practice_common_questions",
        company_name=state.company_name,
        job_title=state.job_title,
        job_description=state.job_description,
        candidate_profile=state.candidate_profile,
        cv_content=state.cv_text,
        alignment_strategy=state.alignment_strategy or state.inferred_role_context or "",
    )
    result = await call_llm(
        task="interview_practice", system=system, user=user, session_id=sid
    )
    action_finish(sid, aid)

    emit_message(sid, result.text)
    return {
        "interview_extras": state.interview_extras
        + [{"kind": "practice", "topic": "common_questions", "content": result.text}],
        "phase": "interview_menu",
    }


async def interview_tech_node(state: ApplicationState) -> dict:
    sid = state.session_id
    seq = len(state.interview_extras)
    emit_message(
        sid,
        "Which topic should I dive into? Reply with the topic, or `pick` and I'll choose one from the JD.",
        key=f"interview_tech:prompt:{seq}",
    )
    reply = interrupt({"kind": "interview_tech_topic"})
    text = (reply or "").strip() if isinstance(reply, str) else ""

    if not text or text.lower() == "pick":
        topic_aid = action_start(sid, "interview_tech_pick", "Picking a topic from the JD")
        topic_result = await call_llm(
            task="interview_tech_pick",
            system=load_system_prompt("chat"),
            user=(
                "Pick the single most likely technical / domain topic this candidate will be "
                "probed on, given the role and JD below. Output ONLY the topic name in 1–6 words.\n\n"
                f"Role: {state.job_title} at {state.company_name}\n\n"
                f"Job description:\n\"\"\"\n{state.job_description[:3000]}\n\"\"\""
            ),
            session_id=sid,
        )
        action_finish(sid, topic_aid)
        topic = topic_result.text.strip().splitlines()[0][:120] or "(JD-derived topic)"
        emit_message(sid, f"Picking **{topic}**.")
    else:
        topic = text

    aid = action_start(sid, "interview_tech", f"Refresher on {topic[:60]}")
    user = render_user_prompt(
        "tech_deep_dive",
        topic=topic,
        company_name=state.company_name,
        job_title=state.job_title,
        job_description=state.job_description,
        candidate_profile=state.candidate_profile,
    )
    result = await call_llm(
        task="interview_tech", system=load_system_prompt("chat"), user=user, session_id=sid
    )
    action_finish(sid, aid)

    emit_message(sid, result.text)
    return {
        "interview_extras": state.interview_extras
        + [{"kind": "tech", "topic": topic, "content": result.text}],
        "phase": "interview_menu",
    }


async def interview_questions_node(state: ApplicationState) -> dict:
    sid = state.session_id
    aid = action_start(sid, "interview_questions", "Drafting questions to ask the interviewer")
    user = render_user_prompt(
        "questions_to_ask",
        company_name=state.company_name,
        job_title=state.job_title,
        job_description=state.job_description,
        company_description=state.company_description,
        interview_context=state.interview_context or "",
        candidate_profile=state.candidate_profile,
    )
    result = await call_llm(
        task="interview_questions",
        system=load_system_prompt("chat"),
        user=user,
        session_id=sid,
    )
    action_finish(sid, aid)

    emit_message(sid, result.text)
    return {
        "interview_extras": state.interview_extras
        + [{"kind": "questions", "topic": "to_ask_interviewer", "content": result.text}],
        "phase": "interview_menu",
    }
