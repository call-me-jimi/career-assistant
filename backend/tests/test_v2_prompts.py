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
    cover_letter="",
    positioning_strategy="",
    previous_briefing="",
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


# ---- v3: journey carry-over sections (briefing) ------------------------------


def test_briefing_v3_journey_sections_render_when_set():
    _clear_cache()
    kwargs = {
        **BRIEFING_KWARGS,
        "cover_letter": "Dear ACME, I am excited...",
        "positioning_strategy": "Lead with platform impact",
        "previous_briefing": "Round 1 prep: focus on basics",
    }
    result = render_user_prompt("generate_interview_briefing", **kwargs, coaching_history=[])
    assert "SUBMITTED COVER LETTER" in result
    assert "Dear ACME, I am excited..." in result
    assert "POSITIONING STRATEGY" in result
    assert "Lead with platform impact" in result
    assert "PREVIOUS BRIEFING FOR THIS JOB" in result
    assert "Round 1 prep: focus on basics" in result


def test_briefing_v3_journey_sections_absent_when_empty():
    _clear_cache()
    result = render_user_prompt("generate_interview_briefing", **BRIEFING_KWARGS, coaching_history=[])
    assert "SUBMITTED COVER LETTER" not in result
    assert "POSITIONING STRATEGY" not in result
    assert "PREVIOUS BRIEFING FOR THIS JOB" not in result


# ---- v3: interview_briefing section (evaluator) -------------------------------


EVALUATOR_KWARGS = dict(
    company_name="ACME",
    job_title="Engineer",
    job_description="Build things",
    candidate_profile="Experienced engineer",
    interview_context="Panel round",
    transcript="[00:00] Hello",
    revision_feedback="",
)


def test_evaluator_v3_briefing_section_renders_when_set():
    _clear_cache()
    result = render_user_prompt(
        "analyze_interview_performance",
        **EVALUATOR_KWARGS,
        interview_briefing="Prep notes: lead with the platform story",
    )
    assert "INTERVIEW BRIEFING THE CANDIDATE PREPARED WITH" in result
    assert "Prep notes: lead with the platform story" in result


def test_evaluator_v3_briefing_section_absent_when_empty():
    _clear_cache()
    result = render_user_prompt(
        "analyze_interview_performance", **EVALUATOR_KWARGS, interview_briefing=""
    )
    assert "INTERVIEW BRIEFING THE CANDIDATE PREPARED WITH" not in result
