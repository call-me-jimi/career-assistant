"""Verify the highest-vN resolver picks up the right files from templates/."""

from backend.llm.prompts import latest_prompt_path, latest_system_path


def test_generate_cover_letter_latest_is_v8():
    assert latest_prompt_path("generate_cover_letter").name == "generate_cover_letter.v8.txt"


def test_simulate_hiring_manager_latest_is_v3():
    # v3 adds the prompt-cache break before the cover letter; the resolver must pick it.
    assert latest_prompt_path("simulate_hiring_manager").name == "simulate_hiring_manager.v3.txt"
    assert latest_system_path("simulate_hiring_manager").name == "simulate_hiring_manager.system.v2.txt"


def test_cover_letter_generation_system_latest_is_v3():
    assert latest_system_path("cover_letter_generation").name == "cover_letter_generation.system.v3.txt"
