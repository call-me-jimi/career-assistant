"""Verify HM feedback JSON parsing handles raw JSON, code fences, surrounding text."""

import pytest

from backend.llm.service import parse_hm_feedback

GOOD = '{"overall_score": 8.7, "decision": "YES", "first_impression": "Strong", "strengths": ["a"], "weaknesses": ["b"], "suggestions": ["c"], "reasoning": "r"}'


def test_parse_raw_json():
    fb = parse_hm_feedback(GOOD)
    assert fb.overall_score == 8.7
    assert fb.decision == "YES"
    assert fb.strengths == ["a"]


def test_parse_with_code_fence():
    wrapped = "```json\n" + GOOD + "\n```"
    fb = parse_hm_feedback(wrapped)
    assert fb.overall_score == 8.7


def test_parse_with_preamble():
    wrapped = "Here is my evaluation:\n\n" + GOOD + "\n\nEnd."
    fb = parse_hm_feedback(wrapped)
    assert fb.decision == "YES"


def test_rejects_out_of_range():
    with pytest.raises(Exception):
        parse_hm_feedback('{"overall_score": 12, "decision": "YES"}')
