"""Confirm extracted job/company info with the user, allow corrections."""

from __future__ import annotations

import re

from langgraph.types import interrupt

from backend.agent.interrupts import emit_message
from backend.agent.state import ApplicationState
from backend.storage.journeys import create_journey, find_journey, update_journey

_JOURNEY_FIELDS = ("job_url", "job_title", "company_name", "location", "job_description", "job_ad_language", "job_screenshot_path")

FIELDS = [
    ("job_title", "Job title"),
    ("company_name", "Company"),
    ("location", "Location"),
]


async def confirm_info_node(state: ApplicationState) -> dict:
    sid = state.session_id
    details_url = f"/session/details?id={sid}"

    lines = []
    for key, label in FIELDS:
        val = getattr(state, key, "") or "—"
        lines.append(f"• **{label}:** {val}")

    summary = (
        "Here's a quick summary:\n\n"
        + "\n".join(lines)
        + "\n\n"
        f"You can also [review all details]({details_url}) → in the full form.\n\n"
        "**Look good?** Just say **yes**, or correct anything inline — e.g. `location: Berlin`."
    )
    emit_message(sid, summary, key="confirm_info:summary")
    reply = interrupt({"kind": "confirm_info", "fields": {
        "job_title": state.job_title,
        "company_name": state.company_name,
        "location": state.location,
    }})

    corrections = _parse_reply(reply)

    final = {
        field: corrections.get(field, getattr(state, field, ""))
        for field in _JOURNEY_FIELDS
    }
    final = {k: v for k, v in final.items() if v}
    jid = state.journey_id
    try:
        if jid:
            await update_journey(jid, **final)
        else:
            existing = await find_journey(
                profile_id=state.profile_id,
                job_url=final.get("job_url", ""),
                company_name=final.get("company_name", ""),
                job_title=final.get("job_title", ""),
            )
            if existing:
                jid = existing["journey_id"]
                await update_journey(jid, **final)
            else:
                jid = await create_journey(profile_id=state.profile_id, **final)
    except Exception:
        pass

    if corrections:
        emit_message(sid, "Updated — moving on.")
        corrections["phase"] = "classify_flow"
        corrections["journey_id"] = jid
        return corrections

    return {"phase": "classify_flow", "journey_id": jid}


def _parse_reply(reply: object) -> dict:
    if isinstance(reply, dict):
        out: dict = {}
        for key in ("job_title", "company_name", "location", "job_description", "company_description"):
            if reply.get(key):
                out[key] = reply[key]
        return out

    if isinstance(reply, str):
        text = reply.strip()
        if text.lower() in {"yes", "y", "ok", "correct", "looks good", "lgtm"}:
            return {}
        patch: dict = {}
        for line in text.split("\n"):
            m = _match_field(line)
            if m:
                patch[m[0]] = m[1]
        return patch

    return {}


_FIELD_ALIASES: dict[str, str] = {
    "job_title": "job_title",
    "title": "job_title",
    "job": "job_title",
    "company_name": "company_name",
    "company": "company_name",
    "location": "location",
    "city": "location",
}


def _match_field(line: str) -> tuple[str, str] | None:
    m = re.match(r"^\s*([a-z_ ]+)\s*:\s*(.+)$", line, re.IGNORECASE)
    if not m:
        return None
    raw_key = m.group(1).strip().lower().replace(" ", "_")
    canonical = _FIELD_ALIASES.get(raw_key)
    if not canonical:
        return None
    return canonical, m.group(2).strip()
