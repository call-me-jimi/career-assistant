"""Tests for scraper's generic schema.org JSON-LD JobPosting handler, which
recovers job content from JS-rendered career sites (Phenom, etc.) that still
embed a complete JobPosting block in the static HTML."""

from __future__ import annotations

import json

from backend.tools import scraper


def _page(job_ld: dict, *, extra_ld: list | None = None) -> str:
    blocks = [job_ld, *(extra_ld or [])]
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks
    )
    return f"<html><head>{scripts}</head><body>Sorry, this job has been filled.</body></html>"


def test_jsonld_extracts_jobposting():
    ld = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": "Data Scientist",
        "hiringOrganization": {"@type": "Organization", "name": "Acme"},
        "jobLocation": {"address": {"addressLocality": "Berlin", "addressCountry": "Germany"}},
        "employmentType": ["FULL_TIME"],
        "identifier": {"@type": "PropertyValue", "value": "R_1"},
        "description": "<h2>Role</h2><p>Build great models here.</p>",
    }
    out = scraper._scrape_jsonld(_page(ld), "https://careers.acme.com/job/1")

    assert out is not None
    assert out["title"] == "Data Scientist - Acme"
    assert "Job Title: Data Scientist" in out["raw_text"]
    assert "Company: Acme" in out["raw_text"]
    assert "Location: Berlin, Germany" in out["raw_text"]
    assert "Type: FULL_TIME" in out["raw_text"]
    assert "Req ID: R_1" in out["raw_text"]
    # HTML tags stripped, block-level text preserved
    assert "Build great models here." in out["raw_text"]
    assert "<h2>" not in out["raw_text"]


def test_jsonld_unescapes_entity_encoded_markup():
    """Phenom sites double-escape the description (``&lt;p&gt;``); it must still
    strip to clean text, not leak literal tags."""
    ld = {
        "@type": "JobPosting",
        "title": "Engineer",
        "description": "&lt;p&gt;Ready for a challenge today?&lt;/p&gt;",
    }
    out = scraper._scrape_jsonld(_page(ld), "https://x/job/2")

    assert out is not None
    assert "Ready for a challenge today?" in out["raw_text"]
    assert "&lt;" not in out["raw_text"]
    assert "<p>" not in out["raw_text"]


def test_jsonld_flattens_graph_container():
    ld = {"@type": "WebPage"}
    graph = {"@graph": [{"@type": "JobPosting", "title": "PM", "description": "<p>Lead.</p>"}]}
    out = scraper._scrape_jsonld(_page(ld, extra_ld=[graph]), "https://x/job/3")

    assert out is not None
    assert out["title"].startswith("PM")
    assert "Lead." in out["raw_text"]


def test_jsonld_returns_none_without_jobposting():
    ld = {"@type": "WebPage", "name": "Careers"}
    assert scraper._scrape_jsonld(_page(ld), "https://x/job/4") is None


def test_jsonld_returns_none_when_description_missing():
    ld = {"@type": "JobPosting", "title": "No body"}
    assert scraper._scrape_jsonld(_page(ld), "https://x/job/5") is None
