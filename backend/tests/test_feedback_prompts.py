"""The employer-feedback and calibration blocks in the v3/v5 templates.

The empty case matters as much as the populated one: a profile with no feedback must
get a prompt byte-identical to the previous version's output.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.agent.nodes.interview_briefing import interview_briefing_node
from backend.agent.nodes.strategy import strategy_node
from backend.agent.state import ApplicationState
from backend.llm.prompts import latest_prompt_path, load_system_prompt, render_user_prompt

FEEDBACK = 'ACME — Staff Engineer (hiring manager, after the final round, 2026-09-01):\n"Wanted sharper ownership stories."'
CALIBRATION = 'ACME — Staff Engineer\nYou assessed: 7.2/10, lean_hire\nThey said: "Wanted more depth."'

STRATEGY_KWARGS = dict(candidate_profile="Experienced engineer", job_profile="Build things")
POSITION_KWARGS = dict(
    candidate_profile="Experienced engineer",
    inferred_role_context="Probably a platform lead role",
    recruiter_job_ad="Confidential client",
)
BRIEFING_KWARGS = dict(
    company_name="ACME",
    job_title="Engineer",
    location="Berlin",
    interview_type="",
    interview_context="First round",
    job_description="Build things",
    company_description="We build things",
    candidate_profile="Experienced engineer",
    cv_content="5 years exp",
    alignment_strategy="Emphasise impact",
    cover_letter="",
    positioning_strategy="",
    previous_briefing="",
    coaching_history=[],
)
EVALUATOR_KWARGS = dict(
    company_name="ACME",
    job_title="Engineer",
    job_description="Build things",
    candidate_profile="Experienced engineer",
    interview_type="",
    interview_context="Panel round",
    interview_briefing="",
    transcript="[00:00] Hello",
    revision_feedback="",
)
SYNTHESIS_KWARGS = dict(
    current_playbook="{}",
    current_candidate_profile="Engineer",
    this_session_signals="{}",
    recent_applications="[]",
)


@pytest.fixture(autouse=True)
def _clear_cache():
    latest_prompt_path.cache_clear()


# ---- the block renders when there is feedback ----------------------------


@pytest.mark.parametrize(
    "stem,kwargs",
    [
        ("generate_alignment_strategy", STRATEGY_KWARGS),
        ("position_candidate", POSITION_KWARGS),
        ("generate_interview_briefing", BRIEFING_KWARGS),
        ("synthesize_learning", SYNTHESIS_KWARGS),
    ],
)
def test_feedback_block_renders_when_present(stem, kwargs):
    result = render_user_prompt(stem, **kwargs, employer_feedback=FEEDBACK)

    assert "WHAT EMPLOYERS ACTUALLY SAID" in result
    assert "Wanted sharper ownership stories." in result


@pytest.mark.parametrize(
    "stem,kwargs",
    [
        ("generate_alignment_strategy", STRATEGY_KWARGS),
        ("position_candidate", POSITION_KWARGS),
        ("generate_interview_briefing", BRIEFING_KWARGS),
        ("synthesize_learning", SYNTHESIS_KWARGS),
    ],
)
def test_feedback_block_absent_when_empty(stem, kwargs):
    result = render_user_prompt(stem, **kwargs, employer_feedback="")

    assert "WHAT EMPLOYERS ACTUALLY SAID" not in result


@pytest.mark.parametrize(
    "stem,kwargs",
    [
        ("generate_alignment_strategy", STRATEGY_KWARGS),
        ("position_candidate", POSITION_KWARGS),
    ],
)
def test_strategy_guardrails_travel_with_the_feedback(stem, kwargs):
    """Injected rejection feedback produces apologetic letters without these."""
    result = render_user_prompt(stem, **kwargs, employer_feedback=FEEDBACK)

    assert "never suggest the letter mention a past rejection" in result.lower()
    assert "data point, not a rule" in result


def test_briefing_guardrails_travel_with_the_feedback():
    result = render_user_prompt(
        "generate_interview_briefing", **BRIEFING_KWARGS, employer_feedback=FEEDBACK
    )

    assert "never suggest raising a past rejection" in result.lower()
    assert "recruiter's form letter" in result


# ---- calibration ---------------------------------------------------------


def test_calibration_block_renders_when_present():
    result = render_user_prompt(
        "analyze_interview_performance", **EVALUATOR_KWARGS, calibration=CALIBRATION
    )

    assert "CALIBRATION" in result
    assert "Wanted more depth." in result


def test_calibration_block_absent_when_empty():
    result = render_user_prompt(
        "analyze_interview_performance", **EVALUATOR_KWARGS, calibration=""
    )

    assert "CALIBRATION" not in result


def test_calibration_tells_the_evaluator_not_to_infer_from_the_outcome():
    """The whole design rests on this: a rejection is not evidence of a bad read."""
    result = render_user_prompt(
        "analyze_interview_performance", **EVALUATOR_KWARGS, calibration=CALIBRATION
    )

    assert "not evidence about your accuracy" in result
    assert "internal hires, frozen budgets" in result
    assert "at least two independent pairs" in result


def test_synthesis_system_prompt_keeps_real_and_simulated_signal_apart():
    system = load_system_prompt("synthesize_learning")

    assert "employer_feedback_themes" in system
    assert "at least two different employers" in system
    assert "Never merge the two" in system


# ---- node wiring ---------------------------------------------------------


def _state(**kw) -> ApplicationState:
    return ApplicationState(session_id="s1", **kw)


@pytest.mark.asyncio
async def test_strategy_passes_feedback_on_the_direct_path():
    captured = {}

    with (
        patch("backend.agent.nodes.strategy.employer_feedback_block", AsyncMock(return_value=FEEDBACK)),
        patch("backend.agent.nodes.strategy.call_llm", AsyncMock(return_value=type("R", (), {"text": "strategy"})())),
        patch("backend.agent.nodes.strategy.render_user_prompt", side_effect=lambda stem, **kw: captured.update({stem: kw}) or "prompt"),
        patch("backend.agent.nodes.strategy.load_system_prompt", return_value="system"),
    ):
        await strategy_node(_state(profile_id="p1", job_source_type="direct"))

    assert captured["generate_alignment_strategy"]["employer_feedback"] == FEEDBACK


@pytest.mark.asyncio
async def test_strategy_passes_feedback_on_the_recruiter_path():
    """The recruiter branch never touches generate_alignment_strategy."""
    captured = {}

    with (
        patch("backend.agent.nodes.strategy.employer_feedback_block", AsyncMock(return_value=FEEDBACK)),
        patch("backend.agent.nodes.strategy.call_llm", AsyncMock(return_value=type("R", (), {"text": "out"})())),
        patch("backend.agent.nodes.strategy.render_user_prompt", side_effect=lambda stem, **kw: captured.update({stem: kw}) or "prompt"),
        patch("backend.agent.nodes.strategy.load_system_prompt", return_value="system"),
    ):
        await strategy_node(_state(profile_id="p1", job_source_type="recruiter"))

    assert captured["position_candidate"]["employer_feedback"] == FEEDBACK


@pytest.mark.asyncio
async def test_strategy_skips_the_lookup_without_a_profile():
    lookup = AsyncMock(return_value=FEEDBACK)

    with (
        patch("backend.agent.nodes.strategy.employer_feedback_block", lookup),
        patch("backend.agent.nodes.strategy.call_llm", AsyncMock(return_value=type("R", (), {"text": "s"})())),
        patch("backend.agent.nodes.strategy.render_user_prompt", return_value="prompt"),
        patch("backend.agent.nodes.strategy.load_system_prompt", return_value="system"),
    ):
        await strategy_node(_state(profile_id=None, job_source_type="direct"))

    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_briefing_passes_feedback():
    captured = {}

    with (
        patch("backend.agent.nodes.interview_briefing.employer_feedback_block", AsyncMock(return_value=FEEDBACK)),
        patch("backend.agent.nodes.interview_briefing.call_llm", AsyncMock(return_value=type("R", (), {"text": "b", "truncated": False})())),
        patch("backend.agent.nodes.interview_briefing.render_user_prompt", side_effect=lambda stem, **kw: captured.update(kw) or "prompt"),
        patch("backend.agent.nodes.interview_briefing.load_system_prompt", return_value="system"),
    ):
        await interview_briefing_node(_state(profile_id="p1"))

    assert captured["employer_feedback"] == FEEDBACK
