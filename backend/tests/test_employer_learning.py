"""Learning from what employers wrote, on each reply (backend/employer_learning.py)."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from backend import employer_learning
from backend.employer_learning import learn_from_employers, schedule_employer_learning
from backend.storage.feedback import add_feedback
from backend.storage.journeys import create_journey
from backend.storage.playbook import get_playbook, upsert_playbook

P1 = "p1"


def _answer(payload: object) -> AsyncMock:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return AsyncMock(return_value=type("R", (), {"text": text})())


async def _reply(company: str, text: str) -> None:
    jid = await create_journey(profile_id=P1, company_name=company, job_title="Head of AI")
    await add_feedback(journey_id=jid, profile_id=P1, source="recruiter", feedback_text=text)


async def test_every_reply_is_read_and_the_lessons_written(test_db):
    await _reply("Rohlik", "Great strengths, but other candidates had more forecasting experience.")
    await _reply("Peec AI", "There isn't an ideal fit at this time.")
    llm = _answer(
        {
            "strengths": [{"theme": "Depth in AI", "evidence": "Rohlik", "count": 1}],
            "concerns": [{"theme": "Forecasting not visible", "evidence": "Rohlik", "count": 1}],
            "unspecific": 1,
        }
    )

    with patch("backend.employer_learning.call_llm", llm):
        assert await learn_from_employers(P1) is True

    prompt = llm.call_args.kwargs["user"]
    assert "forecasting experience" in prompt and "ideal fit" in prompt
    playbook = await get_playbook(P1)
    assert playbook["employer_strengths"] == [
        {"theme": "Depth in AI", "evidence": "Rohlik", "count": 1, "shared": False}
    ]
    assert playbook["employer_feedback_themes"][0]["theme"] == "Forecasting not visible"
    assert playbook["employer_feedback_stats"]["replies"] == 2
    assert playbook["employer_feedback_stats"]["unspecific"] == 1


async def test_the_rest_of_the_playbook_is_left_alone(test_db):
    await upsert_playbook(
        P1, {"recurring_hm_weaknesses": ["vague on scope"], "tone_notes": "direct"}
    )
    await _reply("Rohlik", "Not enough forecasting.")
    llm = _answer({"strengths": [], "concerns": [{"theme": "Forecasting"}], "unspecific": 0})

    with patch("backend.employer_learning.call_llm", llm):
        await learn_from_employers(P1)

    playbook = await get_playbook(P1)
    assert playbook["recurring_hm_weaknesses"] == [{"weakness": "vague on scope", "shared": False}]
    assert playbook["tone_notes"] == "direct"


async def test_a_shared_lesson_stays_shared_while_its_wording_holds(test_db):
    await upsert_playbook(
        P1, {"employer_feedback_themes": [{"theme": "Forecasting", "shared": True}]}
    )
    await _reply("Rohlik", "Not enough forecasting.")
    llm = _answer({"strengths": [], "concerns": [{"theme": "Forecasting", "count": 2}]})

    with patch("backend.employer_learning.call_llm", llm):
        await learn_from_employers(P1)

    assert (await get_playbook(P1))["employer_feedback_themes"][0]["shared"] is True


async def test_a_malformed_answer_keeps_what_was_learned(test_db):
    await upsert_playbook(P1, {"employer_strengths": [{"theme": "Depth in AI"}]})
    await _reply("Rohlik", "Not enough forecasting.")

    with patch("backend.employer_learning.call_llm", _answer("not json")):
        assert await learn_from_employers(P1) is False

    assert (await get_playbook(P1))["employer_strengths"][0]["theme"] == "Depth in AI"


async def test_no_replies_left_clears_the_lessons_without_a_model_call(test_db):
    await upsert_playbook(P1, {"employer_strengths": [{"theme": "Depth in AI"}]})
    llm = _answer({})

    with patch("backend.employer_learning.call_llm", llm):
        await learn_from_employers(P1)

    llm.assert_not_called()
    playbook = await get_playbook(P1)
    assert playbook["employer_strengths"] == []
    assert playbook["employer_feedback_stats"]["replies"] == 0


# --- one run per profile at a time, and no request lost ----------------------


async def test_one_request_learns_once():
    calls: list[str] = []

    async def learn(profile_id: str) -> bool:
        calls.append(profile_id)
        return True

    with patch("backend.employer_learning.learn_from_employers", learn):
        schedule_employer_learning(P1)
        await employer_learning._running[P1]

    assert calls == [P1]
    assert not employer_learning.is_learning(P1)


async def test_requests_arriving_mid_run_are_folded_into_one_more_run():
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def learn(profile_id: str) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return True

    with patch("backend.employer_learning.learn_from_employers", learn):
        schedule_employer_learning(P1)
        task = employer_learning._running[P1]
        await started.wait()
        # Two more replies while the first run is busy: neither starts a run of its own.
        schedule_employer_learning(P1)
        schedule_employer_learning(P1)
        assert employer_learning._running[P1] is task
        release.set()
        await task

    assert calls == 2


async def test_a_failed_run_does_not_stop_the_next():
    calls = 0

    async def learn(profile_id: str) -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("bedrock down")

    with patch("backend.employer_learning.learn_from_employers", learn):
        schedule_employer_learning(P1)
        await employer_learning._running[P1]
        schedule_employer_learning(P1)
        await employer_learning._running[P1]

    assert calls == 2
