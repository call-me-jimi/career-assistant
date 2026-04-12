"""Ask the user step-by-step for any essential fields the extraction missed."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState

REQUIRED_FIELDS = [
    ("job_title", "job title"),
    ("company_name", "company name"),
]

_ASK_TEMPLATES = [
    "The posting doesn't mention the **{label}** — could you fill that in?",
    "I'm also missing the **{label}**. What should I use?",
    "And the **{label}**?",
]


async def fill_missing_info_node(state: ApplicationState) -> dict:
    sid = state.session_id
    updates: dict = {}

    ask_index = 0
    for key, label in REQUIRED_FIELDS:
        if getattr(state, key, ""):
            continue
        template = _ASK_TEMPLATES[min(ask_index, len(_ASK_TEMPLATES) - 1)]
        emit_message(sid, template.format(label=label), key=f"fill_missing:ask:{key}")
        reply = interrupt({"kind": f"ask_field:{key}"})
        value = (reply or "").strip() if isinstance(reply, str) else ""
        if value:
            updates[key] = value
        ask_index += 1

    still_missing = [
        label for key, label in REQUIRED_FIELDS
        if not (updates.get(key) or getattr(state, key, ""))
    ]
    if still_missing:
        emit_message(
            sid,
            f"Still missing: {', '.join(still_missing)} — I'll continue, "
            "but the cover letter may be less targeted.",
            key="fill_missing:still_missing",
        )

    updates["phase"] = "confirm_info"
    return updates
