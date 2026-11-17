"""Round playbooks: one per main round type, and the prompts that include them."""

from backend.llm.prompts import ROUNDS_DIR, render_user_prompt
from backend.storage.interviews import INTERVIEW_TYPES, describe_type, round_playbook
from backend.tests.test_v2_prompts import BRIEFING_KWARGS, MOCK_KWARGS

WITH_PLAYBOOK = {"screening", "hiring_manager", "technical", "panel", "leadership", "final"}

QUESTIONS_KWARGS = {
    "company_name": "ACME",
    "job_title": "Engineer",
    "job_description": "Build things",
    "company_description": "We build things",
    "interview_context": "",
    "candidate_profile": "Experienced",
}


def test_every_playbook_belongs_to_a_round_type():
    slugs = {p.name.split(".")[0] for p in ROUNDS_DIR.glob("*.v*.txt")}
    assert slugs == WITH_PLAYBOOK
    assert slugs <= set(INTERVIEW_TYPES)


def test_each_playbook_has_its_four_parts():
    for slug in WITH_PLAYBOOK:
        text = round_playbook(slug)
        for part in ("Decides:", "Expect:", "Briefing shape:", "Interviewer persona:"):
            assert part in text, (slug, part)


def test_rounds_without_a_playbook_get_none():
    assert round_playbook("other") == ""
    assert round_playbook("case_study") == ""
    assert round_playbook("") == ""


def test_merged_slug_reads_its_new_rounds_playbook():
    assert round_playbook("recruiter") == round_playbook("screening")


def _briefing(slug: str) -> str:
    return render_user_prompt(
        "generate_interview_briefing",
        **{
            **BRIEFING_KWARGS,
            "interview_type": describe_type(slug),
            "round_playbook": round_playbook(slug),
        },
        coaching_history=[],
    )


def test_briefing_includes_the_rounds_playbook_instead_of_the_generic_paragraph():
    text = _briefing("screening")
    assert "ROUND PLAYBOOK" in text
    assert "salary number or range" in text
    assert "a technical round on depth" not in text


def test_briefing_without_a_playbook_keeps_the_generic_paragraph():
    text = _briefing("other")
    assert "ROUND PLAYBOOK" not in text
    assert "a technical round on depth" in text


def test_mock_interviewer_plays_the_rounds_persona():
    text = render_user_prompt(
        "mock_interview_question",
        **{
            **MOCK_KWARGS,
            "interview_type": describe_type("technical"),
            "round_playbook": round_playbook("technical"),
        },
        coaching_history=[],
    )
    assert "INTERVIEW ROUND" in text
    assert 'Play the interviewer described under "Interviewer persona"' in text


def test_questions_to_ask_target_the_round_when_known():
    known = render_user_prompt(
        "questions_to_ask",
        **QUESTIONS_KWARGS,
        interview_type=describe_type("hiring_manager"),
        round_playbook=round_playbook("hiring_manager"),
    )
    unknown = render_user_prompt(
        "questions_to_ask", **QUESTIONS_KWARGS, interview_type="", round_playbook=""
    )
    assert "for the people who run this round" in known
    assert "with all three groups" not in known
    assert "with all three groups" in unknown
