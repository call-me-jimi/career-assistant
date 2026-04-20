"""Collect job info: ask for URL or pasted text, optionally scrape."""

from __future__ import annotations

import re

from langgraph.types import interrupt

from backend.agent.interrupts import action_finish, action_start, emit_message
from backend.agent.state import ApplicationState
from backend.tools.scraper import scrape_job_page


def _parse_page_title(title: str) -> tuple[str, str]:
    """Extract (job_title, company_name) from an HTML page title.

    Handles common patterns: 'Job Title | Company Careers', 'Job Title - Company', etc.
    """
    for sep in (" | ", " - ", " – ", " — ", " at "):
        if sep in title:
            job, company = title.split(sep, 1)
            for suffix in (" Careers", " Jobs", " Recruiting", " Career", " Hiring"):
                company = company.removesuffix(suffix)
            return job.strip(), company.strip()
    return "", ""


def _slug_to_title(url: str) -> str:
    """Convert a URL slug like 'head-of-ai-strategy-32508' to 'Head of AI Strategy'."""
    try:
        slug = url.rstrip("/").split("/")[-1]
        slug = re.sub(r"-\d+$", "", slug)  # strip trailing ID
        return slug.replace("-", " ").title()
    except Exception:
        return ""


async def collect_job_node(state: ApplicationState) -> dict:
    sid = state.session_id

    # If the user reused an existing profile, the greeting already asked for the job.
    # For new users (or those who just saved a new profile), we need to prompt them.
    if not state.profile_reused:
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

            job_title, company_name = _parse_page_title(scraped.get("title", ""))
            if not job_title:
                job_title = _slug_to_title(url)

            return {
                "job_url": url,
                "job_raw_text": scraped["raw_text"],
                "job_title": job_title,
                "company_name": company_name,
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
