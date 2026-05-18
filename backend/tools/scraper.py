"""Minimal job URL scraper.

Strategy: fetch HTML with requests + BS4, strip scripts/styles, return the
visible text. For known JS-heavy platforms (Workable), use their JSON API
instead. The LLM then extracts structured fields via the
`extract_job_and_company_information` prompt — that keeps this tool simple
and avoids per-site scraper fragility.
"""

from __future__ import annotations

import logging
import re

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

_WORKABLE_RE = re.compile(
    r"https?://apply\.workable\.com/(?P<account>[^/]+)/j/(?P<shortcode>[^/?#]+)",
    re.IGNORECASE,
)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    lines = [ln for ln in (ln.strip() for ln in soup.get_text(separator="\n").splitlines()) if ln]
    return "\n".join(lines)


def _scrape_workable(url: str, timeout: int) -> dict[str, str]:
    m = _WORKABLE_RE.match(url)
    account, shortcode = m.group("account"), m.group("shortcode")
    api_url = f"https://apply.workable.com/api/v2/accounts/{account}/jobs/{shortcode}"
    resp = requests.get(api_url, headers={**_HEADERS, "Accept": "application/json"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    title = data.get("title", "")
    company = account.replace("-", " ").title()
    parts = [
        f"Job Title: {title}",
        f"Company: {company}",
    ]
    loc = data.get("location") or {}
    if isinstance(loc, dict) and loc.get("city"):
        parts.append(f"Location: {loc['city']}, {loc.get('country', '')}")
    if data.get("workplace"):
        parts.append(f"Workplace: {data['workplace']}")
    if data.get("type"):
        parts.append(f"Type: {data['type']}")
    for field in ("description", "requirements", "benefits"):
        html = data.get(field) or ""
        if html.strip():
            label = field.capitalize()
            parts.append(f"\n{label}:\n{_html_to_text(html)}")

    raw_text = "\n".join(parts)
    page_title = f"{title} - {company}"
    log.info("scraped workable %s (%d chars via API)", url, len(raw_text))
    return {"url": url, "title": page_title, "raw_text": raw_text}


def scrape_job_page(url: str, timeout: int = 20) -> dict[str, str]:
    """Return {'url', 'title', 'raw_text'} scraped from a job URL."""
    if _WORKABLE_RE.match(url):
        return _scrape_workable(url, timeout)

    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "aside"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "")

    text = soup.get_text(separator="\n", strip=True)
    # Collapse 3+ blank lines to 2 for readability
    lines = [ln for ln in (ln.strip() for ln in text.splitlines()) if ln]
    raw_text = "\n".join(lines)

    log.info("scraped %s (%d chars)", url, len(raw_text))
    return {"url": url, "title": title, "raw_text": raw_text}
