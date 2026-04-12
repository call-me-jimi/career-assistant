"""Minimal job URL scraper.

Strategy: fetch HTML with requests + BS4, strip scripts/styles, return the
visible text. The LLM then extracts structured fields via the
`extract_job_and_company_information` prompt — that keeps this tool simple
and avoids per-site scraper fragility.
"""

from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("assistant.scraper")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def scrape_job_page(url: str, timeout: int = 20) -> dict[str, str]:
    """Return {'url', 'title', 'raw_text'} scraped from a job URL."""
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "")

    text = soup.get_text(separator="\n", strip=True)
    # Collapse 3+ blank lines to 2 for readability
    lines = [ln for ln in (ln.strip() for ln in text.splitlines()) if ln]
    raw_text = "\n".join(lines)

    log.info("scraped %s (%d chars)", url, len(raw_text))
    return {"url": url, "title": title, "raw_text": raw_text}
