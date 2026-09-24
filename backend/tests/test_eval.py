"""backend.eval: scorers, degradations, replay → score → report, ground truth, rating."""

import json

import aiosqlite
import pytest

from backend.eval import judge as judge_mod
from backend.eval import replay as replay_mod
from backend.eval import store
from backend.eval.ground_truth import briefing_questions, evaluator_outcomes
from backend.eval.judge import Judge
from backend.eval.judge_check import degrade, split_letter
from backend.eval.report import render
from backend.eval.score import score_run
from backend.eval.scorers import field_prf, number_grounding, verdict, wilson
from backend.llm.service import LLMCallResult
from backend.storage.traces import record_trace

LETTER = "\n\n".join([
    "Dear Hiring Team,",
    "I led a data team of 9 people and cut platform cost by 50 percent across three years of "
    "steady work on the platform, the pipelines and the models that run the business every day.",
    "Before that I built a recommendation engine that added 500 thousand euros in revenue within "
    "six months, working closely with product, engineering and the commercial teams on rollout.",
    "Kind regards,",
])


# ---------------------------------------------------------------- scorers


def test_number_grounding_flags_only_invented_numbers():
    source = "Team of 9. Cost down 50%. Revenue 500.000 EUR."
    out = "1. Summary\nLed 9 people, cut cost 50 %, added 500,000 EUR and 12 new markets."
    assert number_grounding(out, source) == {"numbers": 4, "ungrounded_numbers": ["12"]}


def test_number_grounding_matches_magnitudes_across_spellings():
    source = "AutoStyling (~€500k in 6 months), 1.5M budget"
    out = "in sechs Monaten 500.000 Euro, Budget 1,5 Mio, 3.5 Jahre"
    assert number_grounding(out, source)["ungrounded_numbers"] == ["3.5"]


def test_field_prf_ignores_list_order_and_case():
    expected = {"title": "Head of Data", "skills": ["Python", "SQL"]}
    pred = {"title": "head of data", "skills": ["SQL", "Python", "Rust"]}
    assert field_prf(pred, expected) == {"precision": 0.75, "recall": 1.0}


def test_wilson_and_verdict():
    lo, hi = wilson(18, 20)
    assert 0.68 < lo < 0.7 and hi > 0.97
    assert verdict(lo, hi) == "switch"
    assert verdict(*wilson(10, 20)) == "inconclusive"
    assert verdict(*wilson(1, 20)) == "keep"


# ---------------------------------------------------------------- judge-check degradations


def test_split_letter_and_degradations():
    user = f'Rubric…\n\nCover Letter:\n"""\n{LETTER}\n"""\n'
    head, letter, tail = split_letter(user)
    assert letter == LETTER and head + letter + tail == user
    variants = degrade(letter)
    assert set(variants) == {"drop_evidence", "generic_opening", "truncated", "wrong_number"}
    assert "team of 9" not in variants["drop_evidence"]  # the paragraph with most numbers
    assert "team of 28" in variants["wrong_number"]
    assert all(v != letter for v in variants.values())


def test_split_letter_without_letter_block():
    assert split_letter("no letter here") is None


# ---------------------------------------------------------------- replay → score → report


async def _trace(task: str, session: str, user: str, response: str, model: str = "claude-opus-4-8") -> None:
    await record_trace(
        session_id=session, card_id=f"{session}-{task}", task=task, provider="anthropic",
        model=model, input_tokens=100, output_tokens=50, duration_ms=1000,
        system_prompt="sys", user_prompt=f"[human] {user}", response_text=response,
    )


async def test_pick_traces_one_per_session_and_single_turn_only(test_db):
    await _trace("cover_letter_generation", "s1", "write", "draft 1")
    await _trace("cover_letter_generation", "s1", "write again", "draft 2")
    await _trace("cover_letter_generation", "s2", "write\n\n[ai] earlier turn", "chat")
    await _trace("cover_letter_generation", "s3", "write", "draft 3")
    ids = await store.pick_traces("cover_letter_generation", last=10)
    cases = await store.load_cases(ids)
    assert [c["response_text"] for c in cases] == ["draft 1", "draft 3"]


def _fake_llm(text: str):
    async def call(**kwargs) -> LLMCallResult:
        return LLMCallResult(text=text, model="m", provider="p", input_tokens=10, output_tokens=5)
    return call


async def test_replay_score_report_end_to_end(test_db, monkeypatch):
    for i in range(3):
        await _trace("cover_letter_generation", f"s{i}", f"CV: team of 9. Job {i}", "baseline letter")
    await store.create_set("cl", "cover_letter_generation",
                           await store.pick_traces("cover_letter_generation", 10))
    monkeypatch.setattr(replay_mod, "call_llm", _fake_llm("GOOD letter, team of 9 and 40 awards"))
    run_id = await replay_mod.run_replay("cl", "claude-opus-5-5", samples=2, assume_yes=True)

    results = await store.list_results(run_id)
    assert [r["side"] for r in results].count("A") == 3  # stored baseline, one each
    assert [r["side"] for r in results].count("B") == 6

    # A judge that prefers whichever output says GOOD, in either position.
    async def judge_llm(*, user, **kwargs) -> LLMCallResult:
        first = user.split("--- Output 2 ---")[0]
        winner = "1" if "GOOD" in first.split("--- Output 1 ---")[1] else "2"
        return LLMCallResult(text=json.dumps({"winner": winner}), model="j", provider="openai")

    monkeypatch.setattr(judge_mod, "call_llm", judge_llm)
    await score_run(run_id, judge_spec="openai:gpt-test", assume_yes=True)

    results = await store.list_results(run_id)
    b = [r for r in results if r["side"] == "B"]
    assert {r["judge_verdict"] for r in b} == {"win"}
    assert b[0]["metrics"]["ungrounded_numbers"] == ["40"]

    text = await render(run_id)
    assert "6 wins / 0 ties / 0 losses" in text
    assert "→ switch" in text
    assert "Only 3 cases" in text


def test_judge_refuses_to_judge_its_own_model():
    judge = Judge("openai:gpt-5.5")
    judge.check_independent("stored", "anthropic:claude-opus-5-5")
    with pytest.raises(ValueError):
        judge.check_independent("stored", "openai:gpt-5.5")


def test_parse_model():
    assert replay_mod.label(replay_mod.parse_model("claude-opus-5-5")) == "anthropic:claude-opus-5-5"
    assert replay_mod.label(replay_mod.parse_model("gpt-5.5")) == "openai:gpt-5.5"
    assert replay_mod.label(replay_mod.parse_model("ollama:llama3.1")) == "ollama:llama3.1"
    with pytest.raises(ValueError):
        replay_mod.parse_model("llama3.1")


# ---------------------------------------------------------------- ground truth


async def test_ground_truth_links_rounds_to_traces(test_db):
    evaluation = {"overall_score": 7, "summary": "Solid round.",
                  "per_question": [{"question": "Why us?"}, {"question": "Biggest failure?"}]}
    await _trace("interview_briefing", "b1", "brief me", "BRIEFING TEXT")
    await _trace("analyze_interview_performance", "e1", "transcript",
                 json.dumps(evaluation))
    async with aiosqlite.connect(test_db) as db:
        await db.execute(
            "INSERT INTO job_journeys (journey_id, profile_id, rejected_at, created_at, updated_at) "
            "VALUES ('j1', 'p1', 300, 0, 0)"
        )
        for iid, at, briefing, ev in (
            ("i1", 100, "BRIEFING TEXT", {"overall_score": 7, "summary": "Solid round."}),
            ("i2", 200, "", {}),
        ):
            await db.execute(
                "INSERT INTO job_interviews (interview_id, journey_id, profile_id, briefing, "
                "evaluation_summary, scheduled_at, created_at, updated_at) "
                "VALUES (?, 'j1', 'p1', ?, ?, ?, 0, 0)",
                (iid, briefing, json.dumps(ev) if ev else "", at),
            )
        await db.commit()
    (briefing_id,) = await store.pick_traces("interview_briefing", 1)
    (eval_id,) = await store.pick_traces("analyze_interview_performance", 1)

    assert await briefing_questions() == {briefing_id: ["Why us?", "Biggest failure?"]}
    # Round i1 was followed by i2, so it advanced even though the job was rejected later.
    assert await evaluator_outcomes() == {eval_id: "advanced"}


# ---------------------------------------------------------------- blind rating


async def test_rate_maps_blind_choice_back_to_candidate(test_db, monkeypatch):
    await _trace("qa", "s1", "question", "baseline answer")
    await store.create_set("qa", "qa", await store.pick_traces("qa", 1))
    monkeypatch.setattr(replay_mod, "call_llm", _fake_llm("candidate answer"))
    run_id = await replay_mod.run_replay("qa", "claude-opus-5-5", samples=1, assume_yes=True)

    from backend.eval import rate as rate_mod

    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))

    def pick_candidate(prompt: str) -> str:
        shown = "\n".join(printed)
        return "1" if shown.index("candidate answer") < shown.index("baseline answer") else "2"

    monkeypatch.setattr("builtins.input", pick_candidate)
    assert await rate_mod.rate_run(run_id) == 1
    b = [r for r in await store.list_results(run_id) if r["side"] == "B"]
    assert b[0]["human_verdict"] == "win"
