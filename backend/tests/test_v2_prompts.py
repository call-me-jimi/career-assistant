"""Smoke tests: v2 templates render without error and produce expected sections."""

import pytest
from backend.llm.prompts import latest_prompt_path, render_user_prompt

BRIEFING_KWARGS = dict(
    company_name="ACME",
    job_title="Engineer",
    location="Berlin",
    interview_context="First round screening",
    job_description="Build things",
    company_description="We build things",
    candidate_profile="Experienced engineer",
    cv_content="5 years exp",
    alignment_strategy="Emphasise impact",
)

MOCK_KWARGS = dict(
    company_name="ACME",
    job_title="Engineer",
    job_description="Build things",
    interview_context="First round",
    candidate_profile="Experienced",
    alignment_strategy="Emphasise impact",
    transcript="(no prior turns)",
    user_request="",
)

PRACTICE_KWARGS = dict(
    company_name="ACME",
    job_title="Engineer",
    job_description="Build things",
    candidate_profile="Experienced",
    cv_content="5 years",
    alignment_strategy="Emphasise impact",
)

HISTORY = [
    {
        "job_title": "SWE",
        "company_name": "OldCo",
        "overall_score": 6.5,
        "decision": "MAYBE",
        "weaknesses": ["no structure", "rambling"],
        "improvements": ["use STAR method"],
        "filler_words": ["um", "like"],
        "pace": "too_fast",
        "clarity": "Rushed",
    }
]


def _clear_cache():
    latest_prompt_path.cache_clear()


def test_briefing_v2_with_history():
    _clear_cache()
    result = render_user_prompt("generate_interview_briefing", **BRIEFING_KWARGS, coaching_history=HISTORY)
    assert "Coaching Reminders" in result
    assert "no structure" in result


def test_briefing_v2_empty_history():
    _clear_cache()
    result = render_user_prompt("generate_interview_briefing", **BRIEFING_KWARGS, coaching_history=[])
    assert "Coaching Reminders" not in result


def test_mock_v2_with_history():
    _clear_cache()
    result = render_user_prompt("mock_interview_question", **MOCK_KWARGS, coaching_history=HISTORY)
    assert "no structure" in result or "rambling" in result


def test_mock_v2_empty_history():
    _clear_cache()
    result = render_user_prompt("mock_interview_question", **MOCK_KWARGS, coaching_history=[])
    assert isinstance(result, str)


def test_practice_v2_with_history():
    _clear_cache()
    result = render_user_prompt("practice_common_questions", **PRACTICE_KWARGS, coaching_history=HISTORY)
    assert "no structure" in result or "rambling" in result


def test_practice_v2_empty_history():
    _clear_cache()
    result = render_user_prompt("practice_common_questions", **PRACTICE_KWARGS, coaching_history=[])
    assert isinstance(result, str)
