"""Minimal job URL scraper.

Strategy: fetch HTML with requests + BS4, strip scripts/styles, return the
visible text. For known JS-heavy platforms (Workable), use their JSON API
instead. The LLM then extracts structured fields via the
`extract_job_and_company_information` prompt — that keeps this tool simple
and avoids per-site scraper fragility.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
from urllib.parse import parse_qs, urlparse

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

_GREENHOUSE_BOARD_RE = re.compile(
    r"boards\.greenhouse\.io/embed/job_board/js\?for=([^&\"'>\s]+)",
    re.IGNORECASE,
)

_WORKDAY_RE = re.compile(
    r"https?://[^/]+\.myworkdayjobs\.com/",
    re.IGNORECASE,
)

_CSOD_RE = re.compile(
    r"https?://(?P<tenant>[^./]+)\.csod\.com/ux/ats/careersite/"
    r"(?P<site>\d+)/home/requisition/(?P<req>\d+)",
    re.IGNORECASE,
)

_ASHBY_RE = re.compile(
    r"https?://jobs\.ashbyhq\.com/(?P<board>[^/?#]+)/(?P<job>[0-9a-fA-F-]{36})",
    re.IGNORECASE,
)

# SAP SuccessFactors "Career Site Builder" sites (e.g. jobs.kpmg.de) render the
# job body client-side via a Stencil web component; the plain HTML holds only
# nav chrome. The component is hosted per-tenant at csbep-{customer}.firebaseapp.com
# and POSTs to the recruiting-solutions.org search API for the job content.
_CSB_HOST_RE = re.compile(r"csbep-([a-z0-9\-]+)\.firebaseapp\.com", re.IGNORECASE)
_CSB_JOBID_RE = re.compile(r"jobID\s*:\s*'(\d+)")
_CSB_SEARCH_API = "https://production.api.recruiting-solutions.org/search"


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    lines = [ln for ln in (ln.strip() for ln in soup.get_text(separator="\n").splitlines()) if ln]
    return "\n".join(lines)


def _iter_jsonld(html: str):
    """Yield every JSON object found in ``application/ld+json`` blocks, flattening
    ``@graph`` containers so nested entities surface at the top level."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for entry in data if isinstance(data, list) else [data]:
            if isinstance(entry, dict) and isinstance(entry.get("@graph"), list):
                yield from (g for g in entry["@graph"] if isinstance(g, dict))
            elif isinstance(entry, dict):
                yield entry


def _scrape_jsonld(html: str, url: str) -> dict[str, str] | None:
    """Extract a schema.org ``JobPosting`` embedded in the page as JSON-LD.

    Many career platforms (Phenom, etc.) render the visible body client-side but
    still emit a complete ``JobPosting`` block in the static HTML. Returns ``None``
    when no such block (with a real description) is present, so the caller can fall
    back to plain-text scraping.
    """
    job = next(
        (e for e in _iter_jsonld(html) if e.get("@type") == "JobPosting" and e.get("description")),
        None,
    )
    if job is None:
        return None

    def _first(val):
        return val[0] if isinstance(val, list) else val

    title = job.get("title", "")
    org = _first(job.get("hiringOrganization")) or {}
    company = org.get("name", "") if isinstance(org, dict) else ""

    parts = [f"Job Title: {title}", f"Company: {company}"]

    addr = (_first(job.get("jobLocation")) or {}).get("address") if job.get("jobLocation") else None
    if isinstance(addr, dict):
        loc = ", ".join(
            v for v in (addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")) if v
        )
        if loc:
            parts.append(f"Location: {loc}")
    emp = job.get("employmentType")
    if emp:
        parts.append(f"Type: {', '.join(emp) if isinstance(emp, list) else emp}")
    ident = _first(job.get("identifier")) or {}
    if isinstance(ident, dict) and ident.get("value"):
        parts.append(f"Req ID: {ident['value']}")

    # Some sites (Phenom) HTML-entity-escape the markup inside the JSON string
    # (``&lt;h2&gt;``); unescape once so the tags are real before stripping them.
    parts.append(f"\nDescription:\n{_html_to_text(html_lib.unescape(job['description']))}")

    raw_text = "\n".join(parts)
    log.info("scraped json-ld JobPosting %s (%d chars)", url, len(raw_text))
    return {"url": url, "title": f"{title} - {company}".strip(" -"), "raw_text": raw_text}


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


def _scrape_greenhouse(board_token: str, job_id: str, url: str, timeout: int) -> dict[str, str]:
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
    resp = requests.get(api_url, headers={**_HEADERS, "Accept": "application/json"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    title = data.get("title", "")
    company = board_token.replace("-", " ").title()
    location = (data.get("location") or {}).get("name", "")

    parts = [f"Job Title: {title}", f"Company: {company}"]
    if location:
        parts.append(f"Location: {location}")
    content_html = data.get("content", "")
    if content_html:
        parts.append(f"\nDescription:\n{_html_to_text(content_html)}")

    raw_text = "\n".join(parts)
    log.info("scraped greenhouse %s via API (%d chars)", url, len(raw_text))
    return {"url": url, "title": f"{title} - {company}", "raw_text": raw_text}


def _scrape_workday(url: str, timeout: int) -> dict[str, str]:
    # Workday pages are fully JS-rendered; scrape the CXS JSON API instead.
    # A detail URL looks like:
    #   https://{tenant}.{dc}.myworkdayjobs.com/{locale}/{site}/job/{jobPath}
    # and its API counterpart is:
    #   https://{host}/wday/cxs/{tenant}/{site}/job/{jobPath}
    parsed = urlparse(url)
    host = parsed.netloc
    tenant = host.split(".")[0]
    segments = [s for s in parsed.path.split("/") if s]
    idx = segments.index("job")
    site = segments[idx - 1]
    job_path = "/".join(segments[idx:])
    api_url = f"https://{host}/wday/cxs/{tenant}/{site}/{job_path}"
    resp = requests.get(api_url, headers={**_HEADERS, "Accept": "application/json"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    info = data.get("jobPostingInfo") or {}

    title = info.get("title", "")
    org_name = (data.get("hiringOrganization") or {}).get("name", "")
    # Workday often prefixes the org name with a numeric entity code ("1000 ACME SE")
    company = re.sub(r"^\d+\s+", "", org_name).strip() or site

    parts = [f"Job Title: {title}", f"Company: {company}"]
    locations = [info.get("location")] + list(info.get("additionalLocations") or [])
    locations = [loc for loc in locations if loc]
    if locations:
        parts.append(f"Location: {', '.join(locations)}")
    if info.get("timeType"):
        parts.append(f"Type: {info['timeType']}")
    if info.get("jobReqId"):
        parts.append(f"Req ID: {info['jobReqId']}")
    desc = info.get("jobDescription") or ""
    if desc.strip():
        parts.append(f"\nDescription:\n{_html_to_text(desc)}")

    raw_text = "\n".join(parts)
    log.info("scraped workday %s via API (%d chars)", url, len(raw_text))
    return {"url": url, "title": f"{title} - {company}", "raw_text": raw_text}


def _scrape_csod(url: str, timeout: int) -> dict[str, str]:
    # Cornerstone OnDemand career sites are fully JS-rendered SPAs; plain HTML
    # scraping yields no job content. The page embeds an anonymous bearer token
    # in a ``csod.context={...}`` script block, which the jobDetails REST
    # endpoint requires:
    #   https://{tenant}.csod.com/services/x/job-requisition/v2/requisitions/{req}/jobDetails
    m = _CSOD_RE.match(url)
    tenant, req_id = m.group("tenant"), m.group("req")
    origin = f"https://{tenant}.csod.com"

    page = requests.get(url, headers=_HEADERS, timeout=timeout)
    page.raise_for_status()
    ctx_match = re.search(r"csod\.context\s*=\s*(\{.*?\});", page.text, re.DOTALL)
    if not ctx_match:
        raise ValueError("csod.context token block not found on page")
    ctx = json.loads(ctx_match.group(1))
    token = ctx["token"]
    culture_id = ctx.get("cultureID", 1)

    api_url = (
        f"{origin}/services/x/job-requisition/v2/requisitions/{req_id}"
        f"/jobDetails?cultureId={culture_id}"
    )
    resp = requests.get(
        api_url,
        headers={**_HEADERS, "Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json().get("data") or {}

    title = data.get("displayTitle", "")
    company = tenant.replace("-", " ").title()
    parts = [f"Job Title: {title}", f"Company: {company}"]

    loc = data.get("primaryLocation") or {}
    loc_parts: list[str] = []
    for key in ("city", "state", "country"):
        val = loc.get(key)
        if val and val not in loc_parts:
            loc_parts.append(val)
    if loc_parts:
        parts.append(f"Location: {', '.join(loc_parts)}")
    if data.get("ref"):
        parts.append(f"Req ID: {data['ref']}")
    desc = data.get("externalDescription") or ""
    if desc.strip():
        parts.append(f"\nDescription:\n{_html_to_text(desc)}")

    raw_text = "\n".join(parts)
    log.info("scraped csod %s via API (%d chars)", url, len(raw_text))
    return {"url": url, "title": f"{title} - {company}", "raw_text": raw_text}


def _scrape_ashby(url: str, timeout: int) -> dict[str, str]:
    # Ashby job pages are fully JS-rendered SPAs; plain HTML scraping yields only
    # the page title. The public posting API returns every listed job for a
    # board, so fetch that and match on the job's UUID:
    #   https://api.ashbyhq.com/posting-api/job-board/{board}
    m = _ASHBY_RE.match(url)
    board, job_id = m.group("board"), m.group("job")
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    resp = requests.get(api_url, headers={**_HEADERS, "Accept": "application/json"}, timeout=timeout)
    resp.raise_for_status()
    jobs = resp.json().get("jobs") or []
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if job is None:
        raise ValueError(f"job {job_id} not found on Ashby board {board!r}")

    title = job.get("title", "")
    company = board.replace("-", " ").title()
    parts = [f"Job Title: {title}", f"Company: {company}"]
    if job.get("location"):
        parts.append(f"Location: {job['location']}")
    if job.get("workplaceType"):
        parts.append(f"Workplace: {job['workplaceType']}")
    if job.get("employmentType"):
        parts.append(f"Type: {job['employmentType']}")
    desc_html = job.get("descriptionHtml") or ""
    if desc_html.strip():
        parts.append(f"\nDescription:\n{_html_to_text(desc_html)}")

    raw_text = "\n".join(parts)
    log.info("scraped ashby %s via API (%d chars)", url, len(raw_text))
    return {"url": url, "title": f"{title} - {company}", "raw_text": raw_text}


def _csb_api_key(customer: str, timeout: int) -> str:
    # The tenant's public search key (``pk_{customer}_…``) lives in a
    # content-hashed Stencil chunk referenced by the app's entry module.
    base = f"https://csbep-{customer}.firebaseapp.com/build/"
    esm = requests.get(base + "csb.esm.js", headers=_HEADERS, timeout=timeout).text
    for chunk in set(re.findall(r"p-[A-Za-z0-9_\-]{6,8}\.js", esm)):
        text = requests.get(base + chunk, headers=_HEADERS, timeout=timeout).text
        m = re.search(r"pk_" + re.escape(customer) + r"_[A-Za-z0-9]+", text)
        if m:
            return m.group(0)
    raise ValueError(f"CSB search key not found for customer {customer!r}")


def _scrape_successfactors_csb(page_html: str, url: str, timeout: int) -> dict[str, str]:
    customer = _CSB_HOST_RE.search(page_html).group(1)
    job_match = _CSB_JOBID_RE.search(page_html)
    if not job_match:
        raise ValueError("CSB jobID not found on page")
    job_id = job_match.group(1)
    api_key = _csb_api_key(customer, timeout)

    body = json.dumps(
        {"count": True, "facets": [], "filter": f"jobId eq '{job_id}' ", "search": "*", "skip": 0}
    )
    resp = requests.post(
        _CSB_SEARCH_API,
        headers={
            **_HEADERS,
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "x-api-key": api_key,
            "customerid": customer,
            "internal": "false",
            "privatejobboard": "false",
        },
        data=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    values = resp.json().get("value") or []
    if not values:
        raise ValueError(f"CSB job {job_id} not found for customer {customer!r}")
    job = values[0]

    soup = BeautifulSoup(page_html, "lxml")
    page_title = soup.title.string.strip() if soup.title and soup.title.string else ""
    company = page_title.split("|")[-1].strip() if "|" in page_title else customer.split("-")[0].title()

    title = job.get("title", "")
    parts = [f"Job Title: {title}", f"Company: {company}"]
    if job.get("city"):
        parts.append(f"Location: {job['city']}")
    if job.get("contractTypes"):
        parts.append(f"Contract: {job['contractTypes']}")
    if job.get("workHours"):
        parts.append(f"Hours: {job['workHours']}")
    for label, field in (
        ("Overview", "description"),
        ("Responsibilities", "tasks"),
        ("Profile", "profile"),
    ):
        html = job.get(field) or ""
        text = _html_to_text(html) if isinstance(html, str) else ""
        if text.strip():
            parts.append(f"\n{label}:\n{text}")

    raw_text = "\n".join(parts)
    log.info("scraped successfactors-csb %s via API (%d chars)", url, len(raw_text))
    return {"url": url, "title": f"{title} - {company}", "raw_text": raw_text}


def scrape_job_page(url: str, timeout: int = 20) -> dict[str, str]:
    """Return {'url', 'title', 'raw_text'} scraped from a job URL."""
    if _WORKABLE_RE.match(url):
        return _scrape_workable(url, timeout)

    if _WORKDAY_RE.match(url) and "/job/" in url:
        return _scrape_workday(url, timeout)

    if _CSOD_RE.match(url):
        return _scrape_csod(url, timeout)

    if _ASHBY_RE.match(url):
        return _scrape_ashby(url, timeout)

    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()

    # Detect Greenhouse embeds (JS-rendered; plain HTML scraping yields nothing)
    board_match = _GREENHOUSE_BOARD_RE.search(resp.text)
    if board_match:
        board_token = board_match.group(1)
        qs = parse_qs(urlparse(url).query)
        job_ids = qs.get("gh_jid") or re.findall(r"gh_jid=(\d+)", resp.text)
        if job_ids:
            return _scrape_greenhouse(board_token, job_ids[0], url, timeout)

    # Detect SuccessFactors Career Site Builder (JS-rendered; body via API)
    if _CSB_HOST_RE.search(resp.text):
        try:
            return _scrape_successfactors_csb(resp.text, url, timeout)
        except Exception:
            log.warning("successfactors-csb handler failed for %s; falling back", url, exc_info=True)

    # Many JS-rendered career sites (Phenom, etc.) still embed a full schema.org
    # JobPosting in the static HTML even when the visible body is client-side only.
    jsonld = _scrape_jsonld(resp.text, url)
    if jsonld is not None:
        return jsonld

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
