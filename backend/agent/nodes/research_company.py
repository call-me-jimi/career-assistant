"""Optional company research step using web search.

Runs after confirm_info. If the extracted company_description is too thin
(under ~200 chars), searches for background info and enriches it via LLM.
Skips silently if TAVILY_API_KEY is not set.
"""

from __future__ import annotations

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.llm.service import call_llm
from backend.tools.web_search import tavily_search

MIN_DESCRIPTION_LENGTH = 200

SUMMARISE_SYSTEM = (
    "You are a research assistant. Given search results about a company, "
    "write a concise but informative company profile (3-5 paragraphs). "
    "Focus on: what the company does, its size/stage, culture, tech stack "
    "or domain, and anything relevant for a job applicant."
)


async def research_company_node(state: ApplicationState) -> dict:
    sid = state.session_id

    if len(state.company_description.strip()) >= MIN_DESCRIPTION_LENGTH:
        return {"phase": "classify_flow"}

    company = state.company_name
    if not company:
        return {"phase": "classify_flow"}

    aid = action_start(sid, "research_company", f"Researching {company}")
    query = f"{company} company overview culture products"
    results = tavily_search(query, max_results=5)

    if not results:
        action_finish(sid, aid, status="ok")
        emit_message(sid, f"Couldn't find more on **{company}** — I'll work with what I have.")
        return {"phase": "classify_flow"}

    snippets = "\n\n".join(
        f"**{r.get('title', '')}**\n{r.get('content', '')}" for r in results
    )

    result = await call_llm(
        task="extract_job_and_company_information",
        system=SUMMARISE_SYSTEM,
        user=f"Company: {company}\nJob title: {state.job_title}\n\nSearch results:\n{snippets}",
        session_id=sid,
    )
    action_finish(sid, aid)

    enriched = f"{state.company_description}\n\n---\n\n{result.text}".strip()
    emit_message(
        sid,
        f"Added some background on **{company}** to the company profile.",
        key="research_company:done",
    )
    return {"company_description": enriched, "phase": "classify_flow"}
