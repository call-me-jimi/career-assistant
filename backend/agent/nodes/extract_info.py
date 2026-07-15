"""Extract structured job + company info from raw page text via LLM."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm, extract_json

_MIN_RAW_TEXT_LENGTH = 200


async def _run_extraction(sid: str, raw_text: str, candidate_profile: str):
    action_id = action_start(sid, "extract_info", "Extracting job & company information")
    system = load_system_prompt("extract_job_and_company_information")
    user = render_user_prompt(
        "extract_job_and_company_information",
        job_description=raw_text,
        company_description="",
        candidate_profile=candidate_profile,
    )
    result = await call_llm(
        task="extract_job_and_company_information",
        system=system,
        user=user,
        session_id=sid,
    )
    action_finish(sid, action_id)

    parsed: dict = {}
    try:
        parsed = extract_json(result.text)
    except Exception:
        parsed = {}

    return parsed, result.text


async def extract_info_node(state: ApplicationState) -> dict:
    sid = state.session_id
    raw_text = state.job_raw_text

    if len(raw_text) < _MIN_RAW_TEXT_LENGTH:
        emit_message(
            sid,
            "I couldn't extract enough content from the URL. "
            "Please paste the full job ad text so I can analyse it properly.",
            key="extract_info:missing_description",
        )
        reply = interrupt({"kind": "collect_job_text"})
        pasted = (reply or {}).get("text", "").strip() if isinstance(reply, dict) else ""
        if pasted:
            raw_text = pasted

    parsed, result_text = await _run_extraction(sid, raw_text, state.candidate_profile)

    job_title = parsed.get("job_title") or parsed.get("title") or state.job_title
    company_name = parsed.get("company_name") or parsed.get("company") or state.company_name
    job_description = parsed.get("job_description") or result_text
    company_description = parsed.get("company_description") or ""
    location = parsed.get("location") or ""
    job_language = (parsed.get("job_language") or "").strip()
    source_raw = (parsed.get("job_source_type") or "").strip().lower()
    job_source_type = "recruiter" if source_raw.startswith("rec") else "direct"

    update: dict = {
        "job_title": job_title,
        "company_name": company_name,
        "job_description": job_description,
        "company_description": company_description,
        "location": location,
        "job_raw_text": raw_text,
        "job_ad_language": job_language,
        "job_source_type": job_source_type,
        "phase": "confirm_info",
    }

    return update
