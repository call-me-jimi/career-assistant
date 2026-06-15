"""Verify the highest-vN resolver picks up the right files from templates/."""

from backend.llm.prompts import latest_prompt_path, latest_system_path


def test_generate_cover_letter_latest_is_v6():
    assert latest_prompt_path("generate_cover_letter").name == "generate_cover_letter.v6.txt"


def test_simulate_hiring_manager_latest_is_v2():
    # We added a v2 for JSON output; the resolver must pick it over v1.
    assert latest_prompt_path("simulate_hiring_manager").name == "simulate_hiring_manager.v2.txt"
    assert latest_system_path("simulate_hiring_manager").name == "simulate_hiring_manager.system.v2.txt"


def test_cover_letter_generation_system_latest_is_v3():
    assert latest_system_path("cover_letter_generation").name == "cover_letter_generation.system.v3.txt"
