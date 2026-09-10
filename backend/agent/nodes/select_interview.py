"""Pick which interview round this session is about.

Interview Prep runs this after `interview_context`, so the briefing it produces is
filed under a specific round. Interview Evaluator runs it before
`evaluator_context`, so it can pull up the briefing that was prepared for the
recording being evaluated instead of whatever briefing the job has most recently.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState
from backend.storage.interviews import (
    INTERVIEW_TYPES,
    create_interview,
    list_interviews,
    resolve_type,
    type_label,
    update_interview,
)

_TYPES_LINE = " · ".join(f"`{label}`" for label, _hint in INTERVIEW_TYPES.values())


def _next_phase(state: ApplicationState) -> str:
    return (
        "interview_briefing"
        if state.assistant_type == "interview_prep"
        else "evaluator_context"
    )


def _format_date(ts: float | int | None) -> str:
    if not ts:
        return "unknown"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _describe(interview: dict) -> str:
    label = (interview.get("label") or "").strip()
    name = type_label(interview.get("interview_type") or "")
    return f"{name} — {label}" if label else name


def _badges(interview: dict) -> str:
    labels = []
    if interview.get("briefing"):
        labels.append(f"briefing ✓ {_format_date(interview.get('briefing_at'))}")
    if interview.get("evaluation_summary"):
        labels.append(f"evaluated ✓ {_format_date(interview.get('evaluation_at'))}")
    return " · ".join(labels) if labels else "nothing recorded yet"


async def select_interview_node(state: ApplicationState) -> dict:
    sid = state.session_id
    is_prep = state.assistant_type == "interview_prep"
    interviews = await list_interviews(state.journey_id) if state.journey_id else []

    question = (
        "Which interview is this briefing for?"
        if is_prep
        else "Which interview should I evaluate?"
    )
    lines = [question, ""]
    if interviews:
        lines += [
            f"{i}. **{_describe(iv)}**  ({_badges(iv)})"
            for i, iv in enumerate(interviews, start=1)
        ]
        lines += ["", f"_Type a number, or name a round type for a new one:_ {_TYPES_LINE}"]
    else:
        lines.append(f"_Name the round type:_ {_TYPES_LINE}")

    emit_message(sid, "\n".join(lines), key=f"select_interview:list:{len(interviews)}")

    options = [
        {"label": f"{i}. {_describe(iv)}", "value": str(i)}
        for i, iv in enumerate(interviews, start=1)
    ] + [{"label": label, "value": slug} for slug, (label, _hint) in INTERVIEW_TYPES.items()]

    reply = interrupt(
        {
            "kind": "select_interview",
            "interviews": [
                {
                    "interview_id": iv["interview_id"],
                    "interview_type": iv["interview_type"],
                    "label": _describe(iv),
                    "has_briefing": bool(iv["briefing"]),
                }
                for iv in interviews
            ],
            "options": options,
        }
    )
    return await _handle_reply(state, interviews, reply)


async def _handle_reply(state: ApplicationState, interviews: list[dict], reply) -> dict:
    sid = state.session_id
    is_prep = state.assistant_type == "interview_prep"
    raw = (reply or "").strip() if isinstance(reply, str) else ""

    if raw.isdigit() and 1 <= int(raw) <= len(interviews):
        return await _continue_round(state, interviews[int(raw) - 1])

    if raw.lower() in {"skip", "none"}:
        emit_message(sid, "Fine — carrying on without pinning this to a round.")
        return {"phase": _next_phase(state)}

    # "technical: pair session with the lead dev" → type + free-text label.
    label = ""
    type_text = raw
    if ":" in raw:
        head, tail = raw.split(":", 1)
        if resolve_type(head):
            type_text, label = head, tail.strip()

    slug = resolve_type(type_text)
    if not slug:
        emit_message(
            state.session_id,
            f"I didn't catch which round that was. Pick a number, or a type: {_TYPES_LINE}",
        )
        return {"phase": "select_interview"}

    interview_id = None
    if state.journey_id:
        try:
            interview_id = await create_interview(
                journey_id=state.journey_id,
                profile_id=state.profile_id,
                interview_type=slug,
                label=label,
                context=state.interview_context or "",
            )
        except Exception:
            pass  # a missing round record must never block the interview flow

    name = type_label(slug) + (f" — {label}" if label else "")
    emit_message(state.session_id, f"Noted — a new **{name}** round for this job.")

    update: dict = {
        "interview_id": interview_id,
        "interview_type": slug,
        "interview_label": label,
        "phase": _next_phase(state),
    }
    if not is_prep:
        # No briefing was prepared for a round that starts here — drop whatever
        # briefing the journey carried in, it belongs to a different round.
        update["interview_briefing"] = ""
    return update


async def _continue_round(state: ApplicationState, interview: dict) -> dict:
    sid = state.session_id
    is_prep = state.assistant_type == "interview_prep"

    if is_prep and state.interview_context and state.interview_context != interview["context"]:
        try:
            await update_interview(interview["interview_id"], context=state.interview_context)
        except Exception:
            pass

    if interview["briefing"]:
        note = (
            f"Working from the briefing I wrote for this round on "
            f"{_format_date(interview.get('briefing_at'))}."
        )
    else:
        note = "No briefing on record for this round."
    emit_message(sid, f"**{_describe(interview)}** it is. {note}")

    return {
        "interview_id": interview["interview_id"],
        "interview_type": interview["interview_type"],
        "interview_label": interview["label"],
        "interview_briefing": interview["briefing"],
        "interview_context": state.interview_context or interview["context"],
        "phase": _next_phase(state),
    }
