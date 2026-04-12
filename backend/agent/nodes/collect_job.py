"""Collect job info: ask for URL or pasted text, optionally scrape."""

from __future__ import annotations

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.tools.scraper import scrape_job_page


async def collect_job_node(state: ApplicationState) -> dict:
    sid = state.session_id

    # If the user came via a saved profile, the greeting already asked for the job.
    # For new users, we need to prompt them.
    if not state.profile_id:
        emit_message(
            sid,
            "Now let's find the job. Paste the URL of the posting, or the job description text directly.",
            key="collect_job:prompt",
        )
    payload = interrupt({"kind": "collect_job"})
    data = payload or {}
    url = (data.get("url") or "").strip() if isinstance(data, dict) else ""
    pasted = (data.get("text") or "").strip() if isinstance(data, dict) else ""

    if url:
        action_id = action_start(sid, "scrape", f"Scraping {url}")
        try:
            scraped = scrape_job_page(url)
            action_finish(sid, action_id)
            emit_message(sid, "Fetched the page — extracting job details.")
            return {
                "job_url": url,
                "job_raw_text": scraped["raw_text"],
                "phase": "extract_info",
            }
        except Exception:
            action_finish(sid, action_id, status="error")
            emit_message(sid, "That URL couldn't be reached. Please paste the job text instead.")
            retry = interrupt({"kind": "collect_job_text"})
            pasted = (retry or {}).get("text", "") if isinstance(retry, dict) else ""

    if pasted:
        emit_message(sid, "Extracting job details from what you pasted.")
        return {
            "job_url": url,
            "job_raw_text": pasted,
            "phase": "extract_info",
        }

    emit_message(sid, "I didn't get any job info. Let's try again.")
    return {"phase": "collect_job"}
