"""Extract structured job + company info from raw page text via LLM."""

from __future__ import annotations

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm, extract_json


async def extract_info_node(state: ApplicationState) -> dict:
    sid = state.session_id
    action_id = action_start(sid, "extract_info", "Extracting job & company information")

    system = load_system_prompt("extract_job_and_company_information")
    user = render_user_prompt(
        "extract_job_and_company_information",
        job_description=state.job_raw_text,
        company_description="",
        candidate_profile=state.candidate_profile,
    )
    result = await call_llm(
        task="extract_job_and_company_information",
        system=system,
        user=user,
        session_id=sid,
    )
    action_finish(sid, action_id)

    # The prompt asks for structured output — parse what we can, fall back to text.
    parsed: dict = {}
    try:
        parsed = extract_json(result.text)
    except Exception:
        parsed = {}

    job_title = parsed.get("job_title") or parsed.get("title") or state.job_title
    company_name = parsed.get("company_name") or parsed.get("company") or state.company_name
    job_description = parsed.get("job_description") or result.text
    company_description = parsed.get("company_description") or ""
    location = parsed.get("location") or ""

    return {
        "job_title": job_title,
        "company_name": company_name,
        "job_description": job_description,
        "company_description": company_description,
        "location": location,
        "phase": "confirm_info",
    }
