"""Prompt caching: templates mark where the stable prefix ends, the service turns
that into a cache breakpoint for Anthropic, and the cost reflects cached tokens."""

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from backend.api.routes import _cost_for
from backend.config import ModelPricing
from backend.llm.prompts import render_user_prompt
from backend.llm.service import CACHE_BREAK, _messages
from backend.observability.callbacks import _split_messages, _usage_from_result

CL_KWARGS = dict(
    applicant_name="Ada",
    job_title="VP Engineering",
    company_name="Acme",
    job_description="JD-TEXT",
    company_description="CO-TEXT",
    candidate_profile="PROFILE-TEXT",
    alignment_strategy="ALIGN-TEXT",
    positioning_strategy="POS-TEXT",
    inferred_role_context="ROLE-TEXT",
    recruiter_name="Acme",
    recruiter_job_ad="JD-TEXT",
    cv_content="CV-TEXT",
    profile_playbook="",
)


def _split(rendered: str) -> tuple[str, str]:
    assert rendered.count(CACHE_BREAK) == 1
    return tuple(rendered.split(CACHE_BREAK))


def test_hm_prompt_caches_everything_but_the_cover_letter():
    head, tail = _split(render_user_prompt(
        "simulate_hiring_manager",
        cv_content="CV-TEXT",
        job_description="JD-TEXT",
        company_description="CO-TEXT",
        cover_letter="LETTER-TEXT",
    ))
    assert "CV-TEXT" in head and "JD-TEXT" in head and "CO-TEXT" in head
    assert "LETTER-TEXT" in tail and "LETTER-TEXT" not in head


def test_cover_letter_prompts_keep_feedback_after_the_break():
    for stem in ("generate_cover_letter", "generate_cover_letter.recruiter"):
        first = render_user_prompt(stem, **CL_KWARGS, hiring_manager_feedback="")
        second = render_user_prompt(stem, **CL_KWARGS, hiring_manager_feedback="FEEDBACK-TEXT")
        head1, tail1 = _split(first)
        head2, tail2 = _split(second)
        # Same prefix on every iteration, so the second draft reads the first one's cache.
        assert head1 == head2
        assert "JD-TEXT" in head1
        assert not tail1.strip()
        assert "FEEDBACK-TEXT" in tail2


def test_anthropic_gets_a_cache_breakpoint():
    msgs = _messages("SYS", f"STABLE\n{CACHE_BREAK}CHANGING", provider="anthropic")
    blocks = msgs[-1].content
    assert blocks[0] == {"type": "text", "text": "STABLE\n", "cache_control": {"type": "ephemeral"}}
    assert blocks[1] == {"type": "text", "text": "CHANGING"}


def test_blank_tail_is_dropped():
    msgs = _messages(None, f"STABLE\n{CACHE_BREAK}\n", provider="anthropic")
    assert len(msgs[-1].content) == 1


def test_other_providers_get_the_marker_removed():
    for provider in ("openai", "ollama"):
        msgs = _messages(None, f"STABLE\n{CACHE_BREAK}CHANGING", provider=provider)
        assert msgs[-1].content == "STABLE\nCHANGING"


def test_trace_shows_block_content_as_text():
    msgs = _messages("SYS", f"STABLE\n{CACHE_BREAK}CHANGING", provider="anthropic")
    system, user = _split_messages([msgs])
    assert system == "SYS"
    assert user == "[human] STABLE\nCHANGING"


def test_usage_reads_cache_tokens_from_usage_metadata():
    msg = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": 10_000,
            "output_tokens": 500,
            "total_tokens": 10_500,
            "input_token_details": {"cache_read": 9_000, "cache_creation": 0,
                                    "ephemeral_5m_input_tokens": 200},
        },
    )
    # Anthropic's raw usage excludes cached tokens; it must not win.
    result = LLMResult(
        generations=[[ChatGeneration(message=msg)]],
        llm_output={"usage": {"input_tokens": 800, "output_tokens": 500}},
    )
    assert _usage_from_result(result) == (10_000, 500, 9_000, 200)


def test_usage_falls_back_to_llm_output():
    result = LLMResult(generations=[[]], llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    assert _usage_from_result(result) == (7, 3, 0, 0)


def test_cost_prices_cache_reads_and_writes():
    pricing = {"m": ModelPricing(input_per_mtok=10.0, output_per_mtok=0.0)}
    assert _cost_for("m", 1_000_000, 0, pricing) == 10.0
    # 1M total: 600k read at 0.1x, 400k written at 1.25x.
    assert abs(_cost_for("m", 1_000_000, 0, pricing, cache_read=600_000, cache_write=400_000) - 5.6) < 1e-9
