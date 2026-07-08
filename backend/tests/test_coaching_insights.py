import pytest
from backend.storage.coaching_insights import save_coaching_insight, get_coaching_history

EVAL = {
    "overall_score": 7.5,
    "decision": "YES",
    "summary": "Solid performance, some gaps",
    "weaknesses": ["no structure", "too verbose"],
    "improvements": ["use STAR", "be concise"],
    "strengths": ["confident", "technical depth"],
    "communication": {
        "filler_words": ["um", "like"],
        "pace": "too_fast",
        "clarity": "Generally clear but rushed",
        "structure": "Needs improvement",
    },
}


@pytest.mark.asyncio
async def test_save_and_load(test_db):
    await save_coaching_insight("p1", "s1", EVAL, "Engineer", "ACME")
    history = await get_coaching_history("p1")

    assert len(history) == 1
    h = history[0]
    assert h["overall_score"] == 7.5
    assert h["decision"] == "YES"
    assert h["weaknesses"] == ["no structure", "too verbose"]
    assert h["improvements"] == ["use STAR", "be concise"]
    assert h["filler_words"] == ["um", "like"]
    assert h["pace"] == "too_fast"
    assert h["clarity"] == "Generally clear but rushed"
    assert h["job_title"] == "Engineer"
    assert h["company_name"] == "ACME"
    assert h["session_id"] == "s1"
    assert h["profile_id"] == "p1"


@pytest.mark.asyncio
async def test_no_profile_id_is_noop(test_db):
    await save_coaching_insight("", "s1", EVAL)
    history = await get_coaching_history("")
    assert history == []


@pytest.mark.asyncio
async def test_none_profile_id_is_noop(test_db):
    await save_coaching_insight(None, "s1", EVAL)
    history = await get_coaching_history(None)
    assert history == []


@pytest.mark.asyncio
async def test_limit_returns_most_recent(test_db):
    for i in range(5):
        eval_copy = {**EVAL, "overall_score": float(i)}
        await save_coaching_insight("p1", f"s{i}", eval_copy, "Role", "Co")

    history = await get_coaching_history("p1", limit=3)
    assert len(history) == 3
    # most recent first: score 4, 3, 2
    assert history[0]["overall_score"] == 4.0
    assert history[2]["overall_score"] == 2.0


@pytest.mark.asyncio
async def test_profile_isolation(test_db):
    await save_coaching_insight("p1", "s1", EVAL)
    await save_coaching_insight("p2", "s2", EVAL)

    assert len(await get_coaching_history("p1")) == 1
    assert len(await get_coaching_history("p2")) == 1
    assert len(await get_coaching_history("p3")) == 0


@pytest.mark.asyncio
async def test_missing_communication_fields(test_db):
    """Partial evaluation dict should not crash."""
    minimal = {
        "overall_score": 5.0,
        "decision": "MAYBE",
        "weaknesses": ["unclear answers"],
        "improvements": [],
    }
    await save_coaching_insight("p1", "s1", minimal)
    history = await get_coaching_history("p1")
    assert history[0]["filler_words"] == []
    assert history[0]["pace"] is None
    assert history[0]["clarity"] is None
