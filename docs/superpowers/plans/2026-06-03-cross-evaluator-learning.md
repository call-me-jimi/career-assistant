# Cross-Evaluator Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist key signals from accepted interview evaluations to a per-profile coaching record, then surface that history in future interview prep sessions to personalise briefings, mock questions, and practice answers.

**Architecture:** A new `coaching_insights` SQLite table stores evaluation signals (weaknesses, improvements, speech habits) keyed by `profile_id` on every accepted evaluation. A new `load_coaching_history` LangGraph node runs silently after `greeting` in the interview prep graph, loading recent insights into `ApplicationState.coaching_history`. Three v2 Jinja2 prompt templates inject the coaching history into briefing generation, mock question selection, and practice answer generation.

**Tech Stack:** Python 3.12, aiosqlite, LangGraph, Pydantic v2, Jinja2 (StrictUndefined), uv, pytest, pytest-asyncio

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/storage/db.py` | Add `coaching_insights` table + index to SCHEMA |
| Create | `backend/storage/coaching_insights.py` | `save_coaching_insight` + `get_coaching_history` |
| Modify | `backend/agent/state.py` | Add `coaching_history: list[dict]` field |
| Modify | `backend/agent/nodes/evaluator.py` | Call save on accept; import helper |
| Create | `backend/agent/nodes/load_coaching_history.py` | Silent load node for interview prep graph |
| Modify | `backend/agent/graph_interview.py` | Wire new node between greeting and cv_intake |
| Modify | `backend/agent/nodes/interview_briefing.py` | Pass `coaching_history` arg to render_user_prompt |
| Modify | `backend/agent/nodes/interview_extras.py` | Pass `coaching_history` arg to mock + practice renders |
| Create | `backend/templates/prompts/generate_interview_briefing.v2.txt` | Briefing template with coaching reminders section |
| Create | `backend/templates/prompts/mock_interview_question.v2.txt` | Mock question template targeting documented weaknesses |
| Create | `backend/templates/prompts/practice_common_questions.v2.txt` | Practice template addressing past weaknesses |
| Create | `tests/conftest.py` | Shared async DB fixture |
| Create | `tests/storage/test_coaching_insights.py` | Storage CRUD tests |
| Create | `tests/nodes/test_load_coaching_history.py` | Load node unit test |
| Create | `tests/templates/test_v2_prompts.py` | Template rendering smoke tests |

---

## ⚠️ Critical Deployment Note

`backend/llm/prompts.py` uses `@lru_cache` on `latest_prompt_path` and `StrictUndefined` in the Jinja2 environment.

- **StrictUndefined** means: if a v2 template references `coaching_history` but the node doesn't pass the kwarg, the render call **crashes**.
- **lru_cache** means: template paths are resolved once at server startup. Adding v2 files while the server runs has no effect until restart.

**Required order within a restart cycle:**
1. Add `coaching_history=state.coaching_history` kwargs to the render calls (Tasks 6a/6b) — these are silently ignored by v1 templates (Jinja2 ignores extra kwargs).
2. Add the v2 template files (Task 7).
3. Restart the server.

Tasks 6a/6b must be committed before Task 7. Never deploy Task 7 without Task 6a/6b.

---

## Task 1: DB Schema

**Files:**
- Modify: `backend/storage/db.py`

- [ ] **Step 1: Add the table to SCHEMA**

In `backend/storage/db.py`, append to the `SCHEMA` string (after the last `CREATE INDEX` line, before the closing `"""`):

```sql

CREATE TABLE IF NOT EXISTS coaching_insights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id    TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    job_title     TEXT NOT NULL DEFAULT '',
    company_name  TEXT NOT NULL DEFAULT '',
    overall_score REAL,
    decision      TEXT,
    summary       TEXT NOT NULL DEFAULT '',
    weaknesses    TEXT NOT NULL DEFAULT '[]',
    improvements  TEXT NOT NULL DEFAULT '[]',
    filler_words  TEXT NOT NULL DEFAULT '[]',
    pace          TEXT,
    clarity       TEXT,
    created_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coaching_insights_profile
    ON coaching_insights(profile_id, created_at DESC);
```

- [ ] **Step 2: Verify schema is idempotent**

```bash
uv run python -c "
import asyncio
from backend.storage.db import init_db
asyncio.run(init_db())
asyncio.run(init_db())   # second call must not error
print('OK')
"
```

Expected: `OK` (no error on double init).

- [ ] **Step 3: Commit**

```bash
git add backend/storage/db.py
git commit -m "feat: add coaching_insights table for cross-evaluator learning"
```

---

## Task 2: Storage Module + Tests

**Files:**
- Create: `backend/storage/coaching_insights.py`
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`
- Create: `tests/storage/__init__.py`
- Create: `tests/storage/test_coaching_insights.py`

- [ ] **Step 1: Install test dependencies**

```bash
uv add --dev pytest pytest-asyncio
```

- [ ] **Step 2: Write the failing tests**

Create `tests/__init__.py` (empty) and `tests/storage/__init__.py` (empty).

Create `tests/conftest.py`:

```python
import asyncio
import pytest
import aiosqlite
import backend.storage.db as db_module
from backend.storage.db import SCHEMA, _migrate


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """Temp SQLite DB with full schema; patches DB_PATH for the duration."""
    path = tmp_path / "test.sqlite"
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await _migrate(db)
        await db.commit()
    monkeypatch.setattr(db_module, "DB_PATH", path)
    return path
```

Create `tests/storage/test_coaching_insights.py`:

```python
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
```

- [ ] **Step 3: Run tests — expect FAIL (module missing)**

```bash
uv run pytest tests/storage/test_coaching_insights.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` on `coaching_insights`.

- [ ] **Step 4: Implement `backend/storage/coaching_insights.py`**

```python
"""Per-profile coaching insights from past interview evaluations."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

from backend.storage.db import connect


async def save_coaching_insight(
    profile_id: str | None,
    session_id: str,
    evaluation_dict: dict[str, Any],
    job_title: str = "",
    company_name: str = "",
) -> None:
    if not profile_id:
        return
    comm = evaluation_dict.get("communication") or {}
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO coaching_insights
                (profile_id, session_id, job_title, company_name,
                 overall_score, decision, summary,
                 weaknesses, improvements, filler_words, pace, clarity, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                session_id,
                job_title or "",
                company_name or "",
                evaluation_dict.get("overall_score"),
                evaluation_dict.get("decision"),
                evaluation_dict.get("summary", ""),
                json.dumps(evaluation_dict.get("weaknesses") or []),
                json.dumps(evaluation_dict.get("improvements") or []),
                json.dumps(comm.get("filler_words") or []),
                comm.get("pace"),
                comm.get("clarity"),
                time.time(),
            ),
        )
        await db.commit()


async def get_coaching_history(
    profile_id: str | None, limit: int = 3
) -> list[dict[str, Any]]:
    if not profile_id:
        return []
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT profile_id, session_id, job_title, company_name,
                   overall_score, decision, summary,
                   weaknesses, improvements, filler_words, pace, clarity, created_at
            FROM coaching_insights
            WHERE profile_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (profile_id, limit),
        )
        rows = await cur.fetchall()
    return [
        {
            "profile_id": row["profile_id"],
            "session_id": row["session_id"],
            "job_title": row["job_title"],
            "company_name": row["company_name"],
            "overall_score": row["overall_score"],
            "decision": row["decision"],
            "summary": row["summary"],
            "weaknesses": json.loads(row["weaknesses"]),
            "improvements": json.loads(row["improvements"]),
            "filler_words": json.loads(row["filler_words"]),
            "pace": row["pace"],
            "clarity": row["clarity"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
uv run pytest tests/storage/test_coaching_insights.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/storage/coaching_insights.py tests/conftest.py tests/__init__.py tests/storage/__init__.py tests/storage/test_coaching_insights.py
git commit -m "feat: coaching_insights storage module with tests"
```

---

## Task 3: ApplicationState Field

**Files:**
- Modify: `backend/agent/state.py`

- [ ] **Step 1: Add the field**

In `backend/agent/state.py`, find the `# Interview prep` block (around line 88) and add `coaching_history` as the last field in that block:

```python
# Cross-session coaching context (loaded at interview prep session start if profile_id is known)
coaching_history: list[dict[str, Any]] = Field(default_factory=list)
```

The `Any` import is already present (`from typing import Any`).

- [ ] **Step 2: Verify Pydantic accepts the field**

```bash
uv run python -c "
from backend.agent.state import ApplicationState
s = ApplicationState(session_id='x', assistant_type='interview_prep', language='English')
assert s.coaching_history == []
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/agent/state.py
git commit -m "feat: add coaching_history field to ApplicationState"
```

---

## Task 4: Save Coaching Insight on Evaluation Accept

**Files:**
- Modify: `backend/agent/nodes/evaluator.py`

- [ ] **Step 1: Modify the accept branch**

In `backend/agent/nodes/evaluator.py`, find the accept branch at line ~195:

```python
    if not text or lowered in {"accept", "ok", "looks good", "yes"}:
        return {"phase": "export"}
```

Replace it with:

```python
    if not text or lowered in {"accept", "ok", "looks good", "yes"}:
        if state.profile_id and state.interview_evaluation:
            try:
                from backend.storage.coaching_insights import save_coaching_insight
                await save_coaching_insight(
                    profile_id=state.profile_id,
                    session_id=state.session_id,
                    evaluation_dict=state.interview_evaluation,
                    job_title=state.job_title,
                    company_name=state.company_name,
                )
            except Exception:
                pass  # never block the accept flow
        return {"phase": "export"}
```

- [ ] **Step 2: Verify no syntax errors**

```bash
uv run python -c "from backend.agent.nodes.evaluator import evaluator_review_node; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/agent/nodes/evaluator.py
git commit -m "feat: save coaching insights to DB when evaluation is accepted"
```

---

## Task 5: Load Node + Graph Wiring + Tests

**Files:**
- Create: `backend/agent/nodes/load_coaching_history.py`
- Modify: `backend/agent/graph_interview.py`
- Create: `tests/nodes/__init__.py`
- Create: `tests/nodes/test_load_coaching_history.py`

- [ ] **Step 1: Write the failing test**

Create `tests/nodes/__init__.py` (empty).

Create `tests/nodes/test_load_coaching_history.py`:

```python
from unittest.mock import AsyncMock, patch
import pytest

from backend.agent.nodes.load_coaching_history import load_coaching_history_node
from backend.agent.state import ApplicationState


def _state(**kwargs) -> ApplicationState:
    defaults = dict(session_id="s1", assistant_type="interview_prep", language="English")
    return ApplicationState(**{**defaults, **kwargs})


@pytest.mark.asyncio
async def test_loads_history_when_profile_id_set():
    history = [{"overall_score": 7.0, "decision": "YES", "weaknesses": ["rambling"]}]
    with patch(
        "backend.agent.nodes.load_coaching_history.get_coaching_history",
        new=AsyncMock(return_value=history),
    ):
        result = await load_coaching_history_node(_state(profile_id="p1"))
    assert result == {"coaching_history": history}


@pytest.mark.asyncio
async def test_noop_when_no_profile_id():
    with patch(
        "backend.agent.nodes.load_coaching_history.get_coaching_history",
        new=AsyncMock(return_value=[]),
    ) as mock_get:
        result = await load_coaching_history_node(_state(profile_id=None))
    assert result == {}
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_noop_when_empty_profile_id():
    with patch(
        "backend.agent.nodes.load_coaching_history.get_coaching_history",
        new=AsyncMock(return_value=[]),
    ) as mock_get:
        result = await load_coaching_history_node(_state(profile_id=""))
    assert result == {}
    mock_get.assert_not_called()
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

```bash
uv run pytest tests/nodes/test_load_coaching_history.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `backend/agent/nodes/load_coaching_history.py`**

```python
"""Silently load per-profile coaching history for interview prep sessions."""

from __future__ import annotations

from backend.agent.state import ApplicationState
from backend.storage.coaching_insights import get_coaching_history


async def load_coaching_history_node(state: ApplicationState) -> dict:
    if not state.profile_id:
        return {}
    history = await get_coaching_history(state.profile_id, limit=3)
    return {"coaching_history": history}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/nodes/test_load_coaching_history.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Wire the node into `graph_interview.py`**

In `backend/agent/graph_interview.py`:

Add import after the existing node imports (around line 19):
```python
from backend.agent.nodes.load_coaching_history import load_coaching_history_node
```

Add node registration after `g.add_node("greeting", greeting_node)` (around line 37):
```python
    g.add_node("load_coaching_history", load_coaching_history_node)
```

Replace the existing edge (line ~56):
```python
    g.add_edge("greeting", "cv_intake")
```
with:
```python
    g.add_edge("greeting", "load_coaching_history")
    g.add_edge("load_coaching_history", "cv_intake")
```

- [ ] **Step 6: Verify the graph builds**

```bash
uv run python -c "
from backend.agent.graph_interview import build_interview_graph

class FakeCheckpointer:
    pass

g = build_interview_graph(FakeCheckpointer())
print('OK')
"
```

Expected: `OK` (no import or graph compilation error).

- [ ] **Step 7: Commit**

```bash
git add backend/agent/nodes/load_coaching_history.py backend/agent/graph_interview.py tests/nodes/__init__.py tests/nodes/test_load_coaching_history.py
git commit -m "feat: load coaching history node in interview prep graph"
```

---

## Task 6a: Pass `coaching_history` to `interview_briefing_node`

**Files:**
- Modify: `backend/agent/nodes/interview_briefing.py`

> Must deploy before Task 7 (v2 templates). Safe with v1 — Jinja2 ignores unused kwargs.

- [ ] **Step 1: Add the kwarg**

In `backend/agent/nodes/interview_briefing.py`, find the `render_user_prompt` call (lines ~17-28) and add `coaching_history=state.coaching_history` as the last argument:

```python
    user = render_user_prompt(
        "generate_interview_briefing",
        company_name=state.company_name,
        job_title=state.job_title,
        location=state.location,
        interview_context=state.interview_context or "",
        job_description=state.job_description,
        company_description=state.company_description,
        candidate_profile=state.candidate_profile,
        cv_content=state.cv_text,
        alignment_strategy=state.alignment_strategy or state.inferred_role_context or "",
        coaching_history=state.coaching_history,
    )
```

- [ ] **Step 2: Verify no syntax errors**

```bash
uv run python -c "from backend.agent.nodes.interview_briefing import interview_briefing_node; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/agent/nodes/interview_briefing.py
git commit -m "feat: pass coaching_history to interview briefing prompt"
```

---

## Task 6b: Pass `coaching_history` to `interview_extras` Nodes

**Files:**
- Modify: `backend/agent/nodes/interview_extras.py`

> Must deploy before Task 7 (v2 templates). Safe with v1.

- [ ] **Step 1: Add kwarg to `mock_interview_node`**

In `backend/agent/nodes/interview_extras.py`, find the `render_user_prompt("mock_interview_question", ...)` call (lines ~109-119) and add `coaching_history=state.coaching_history` as the last argument:

```python
        user_prompt = render_user_prompt(
            "mock_interview_question",
            company_name=state.company_name,
            job_title=state.job_title,
            job_description=state.job_description[:3000],
            interview_context=state.interview_context or "",
            candidate_profile=state.candidate_profile[:2500],
            alignment_strategy=state.alignment_strategy or state.inferred_role_context or "",
            transcript=_format_transcript(turns),
            user_request=last_user,
            coaching_history=state.coaching_history,
        )
```

- [ ] **Step 2: Add kwarg to `interview_practice_node`**

Find the `render_user_prompt("practice_common_questions", ...)` call (lines ~199-207) and add `coaching_history=state.coaching_history` as the last argument:

```python
    user = render_user_prompt(
        "practice_common_questions",
        company_name=state.company_name,
        job_title=state.job_title,
        job_description=state.job_description,
        candidate_profile=state.candidate_profile,
        cv_content=state.cv_text,
        alignment_strategy=state.alignment_strategy or state.inferred_role_context or "",
        coaching_history=state.coaching_history,
    )
```

- [ ] **Step 3: Verify no syntax errors**

```bash
uv run python -c "from backend.agent.nodes.interview_extras import mock_interview_node, interview_practice_node; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/agent/nodes/interview_extras.py
git commit -m "feat: pass coaching_history to mock interview and practice prompts"
```

---

## Task 7: v2 Prompt Templates + Smoke Tests

**Files:**
- Create: `backend/templates/prompts/generate_interview_briefing.v2.txt`
- Create: `backend/templates/prompts/mock_interview_question.v2.txt`
- Create: `backend/templates/prompts/practice_common_questions.v2.txt`
- Create: `tests/templates/__init__.py`
- Create: `tests/templates/test_v2_prompts.py`

> These files make v2 live. The `lru_cache` means they only take effect after a server restart. Deploy Tasks 6a + 6b first.

- [ ] **Step 1: Write the smoke tests first**

Create `tests/templates/__init__.py` (empty).

Create `tests/templates/test_v2_prompts.py`:

```python
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
    result = render_user_prompt(**BRIEFING_KWARGS, coaching_history=HISTORY)
    assert "Coaching Reminders" in result
    assert "no structure" in result
    assert "STAR method" in result


def test_briefing_v2_empty_history():
    _clear_cache()
    result = render_user_prompt(**BRIEFING_KWARGS, coaching_history=[])
    assert "Coaching Reminders" not in result


def test_mock_v2_with_history():
    _clear_cache()
    result = render_user_prompt("mock_interview_question", **MOCK_KWARGS, coaching_history=HISTORY)
    assert "no structure" in result or "rambling" in result


def test_mock_v2_empty_history():
    _clear_cache()
    result = render_user_prompt("mock_interview_question", **MOCK_KWARGS, coaching_history=[])
    assert isinstance(result, str)  # just renders without error


def test_practice_v2_with_history():
    _clear_cache()
    result = render_user_prompt("practice_common_questions", **PRACTICE_KWARGS, coaching_history=HISTORY)
    assert "no structure" in result or "rambling" in result


def test_practice_v2_empty_history():
    _clear_cache()
    result = render_user_prompt("practice_common_questions", **PRACTICE_KWARGS, coaching_history=[])
    assert isinstance(result, str)


def test_briefing_stem():
    _clear_cache()
    render_user_prompt(**BRIEFING_KWARGS, coaching_history=[])
```

Note: `render_user_prompt` for briefing uses `stem="generate_interview_briefing"` implicitly through the first positional argument. Add the stem explicitly:

Replace `render_user_prompt(**BRIEFING_KWARGS, ...)` with `render_user_prompt("generate_interview_briefing", **BRIEFING_KWARGS, ...)` in the test file (correct the calls):

```python
def test_briefing_v2_with_history():
    _clear_cache()
    result = render_user_prompt("generate_interview_briefing", **BRIEFING_KWARGS, coaching_history=HISTORY)
    assert "Coaching Reminders" in result
    assert "no structure" in result
    assert "STAR method" in result


def test_briefing_v2_empty_history():
    _clear_cache()
    result = render_user_prompt("generate_interview_briefing", **BRIEFING_KWARGS, coaching_history=[])
    assert "Coaching Reminders" not in result


def test_practice_v2_with_history():
    _clear_cache()
    result = render_user_prompt("practice_common_questions", **PRACTICE_KWARGS, coaching_history=HISTORY)
    assert "no structure" in result or "rambling" in result


def test_practice_v2_empty_history():
    _clear_cache()
    result = render_user_prompt("practice_common_questions", **PRACTICE_KWARGS, coaching_history=[])
    assert isinstance(result, str)
```

- [ ] **Step 2: Run tests — expect FAIL (v2 files missing, falls back to v1 which doesn't produce expected sections)**

```bash
uv run pytest tests/templates/test_v2_prompts.py -v
```

Expected: failures on `test_briefing_v2_with_history`, `test_mock_v2_with_history`, `test_practice_v2_with_history` (sections not present in v1).

- [ ] **Step 3: Create `backend/templates/prompts/generate_interview_briefing.v2.txt`**

```
Prepare an interview briefing for this specific upcoming interview.

Write directly to the candidate in second person. Follow the section structure defined in the system prompt. Ground every suggestion in the inputs below and do not invent facts.

--------------------------------------------------
ROLE INFORMATION

Company:
{{ company_name }}

Job Title:
{{ job_title }}

Location:
{{ location }}

--------------------------------------------------
INTERVIEW CONTEXT (from the company, if provided)
"""
{{ interview_context }}
"""

If this section is empty, assume a first-round screening and say so explicitly in the interview snapshot.

--------------------------------------------------
JOB DESCRIPTION
"""
{{ job_description }}
"""

--------------------------------------------------
COMPANY DESCRIPTION
"""
{{ company_description }}
"""

--------------------------------------------------
CANDIDATE PROFILE
"""
{{ candidate_profile }}
"""

--------------------------------------------------
CANDIDATE CV (raw)
"""
{{ cv_content }}
"""

--------------------------------------------------
ALIGNMENT STRATEGY (how the candidate plans to position for this role)
"""
{{ alignment_strategy }}
"""

--------------------------------------------------
{% if coaching_history %}
COACHING REMINDERS FROM PAST INTERVIEWS

The candidate has {{ coaching_history | length }} prior interview evaluation(s) on record. Use this to personalise the briefing — surface recurring weaknesses as actionable reminders. Do not repeat strengths; the candidate already knows what they do well.

{% for entry in coaching_history %}
Interview {{ loop.index }}{% if entry.job_title %} — {{ entry.job_title }}{% if entry.company_name %} at {{ entry.company_name }}{% endif %}{% endif %} (score: {{ entry.overall_score }}/10, outcome: {{ entry.decision }}):
  Weaknesses: {{ entry.weaknesses | join("; ") if entry.weaknesses else "none recorded" }}
  Work on: {{ entry.improvements | join("; ") if entry.improvements else "none recorded" }}{% if entry.filler_words %}
  Speech habits to fix: filler words — {{ entry.filler_words | join(", ") }}; pace — {{ entry.pace or "not noted" }}{% endif %}
{% endfor %}

After the main briefing sections, add a "## Coaching Reminders" section. Write 3–5 bullet points that directly reference the patterns above. Be concrete and direct: "In your last interview you tended to [X] — this time [specific fix]." Do not be vague or encouraging without substance.
{% endif %}

--------------------------------------------------

Produce the briefing now, in Markdown, following the section order from the system prompt. Output the briefing only.
```

- [ ] **Step 4: Create `backend/templates/prompts/mock_interview_question.v2.txt`**

```
You are conducting a mock interview for the role below. Ask the candidate ONE question.

Pick the question to be realistic for this exact interview round and the candidate's profile. Vary topic from previous questions in the transcript: if the last question was behavioural, lean technical; if it was about scope, lean about depth; etc. Avoid generic questions that don't probe their real fit.

If the candidate just asked for a "different" topic, deliberately switch dimension (technical ↔ behavioural ↔ situational ↔ stakeholder).

ROLE
{{ job_title }} at {{ company_name }}

JOB DESCRIPTION (extracts)
"""
{{ job_description }}
"""

INTERVIEW CONTEXT
"""
{{ interview_context }}
"""

CANDIDATE PROFILE
"""
{{ candidate_profile }}
"""

ALIGNMENT STRATEGY
"""
{{ alignment_strategy }}
"""

PREVIOUS TRANSCRIPT (for context — do not repeat questions)
"""
{{ transcript }}
"""

USER REQUEST (optional steering)
"""
{{ user_request }}
"""

{% if coaching_history %}
DOCUMENTED WEAK AREAS FROM PAST REAL INTERVIEWS
{% for entry in coaching_history %}
Evaluation {{ loop.index }}{% if entry.job_title %} ({{ entry.job_title }}{% if entry.company_name %} at {{ entry.company_name }}{% endif %}, score {{ entry.overall_score }}/10){% endif %}:
  Weaknesses: {{ entry.weaknesses | join("; ") if entry.weaknesses else "none" }}{% if entry.filler_words %}
  Speech: filler words — {{ entry.filler_words | join(", ") }}; pace — {{ entry.pace or "not noted" }}{% endif %}
{% endfor %}

Bias your question selection toward the candidate's documented weak areas above. For example: if they lacked structure, choose a question that rewards a structured answer (e.g. "walk me through…"). If they were verbose, choose a question that punishes rambling (e.g. a precise technical "what is the difference between…").
{% endif %}

Output ONLY the question itself, in 1–3 sentences. No preamble, no "here is your question". Speak as the interviewer.
```

- [ ] **Step 5: Create `backend/templates/prompts/practice_common_questions.v2.txt`**

```
Prepare polished sample answers to the most common interview questions for this candidate, this role, and this company.

Cover at least:
1. "Tell me about yourself"
2. "Why this company / why this role"
3. "What's your biggest weakness"
4. "Tell me about a time you ..." (pick the most relevant behavioural prompt for this role: leadership, conflict, ambiguity, technical depth — your choice)
5. "Where do you see yourself in 3–5 years"

For each question, write a first-person answer the candidate can adapt: 4–8 sentences, grounded in their real CV and the alignment strategy. Lead each with the strongest hook for *this* role.

ROLE
{{ job_title }} at {{ company_name }}

JOB DESCRIPTION
"""
{{ job_description }}
"""

CANDIDATE PROFILE
"""
{{ candidate_profile }}
"""

CANDIDATE CV (raw)
"""
{{ cv_content }}
"""

ALIGNMENT STRATEGY
"""
{{ alignment_strategy }}
"""

{% if coaching_history %}
CANDIDATE'S DOCUMENTED WEAKNESSES FROM PAST EVALUATIONS
{% for entry in coaching_history %}
Evaluation {{ loop.index }}{% if entry.job_title %} ({{ entry.job_title }}{% if entry.company_name %} at {{ entry.company_name }}{% endif %}){% endif %}:
  {{ entry.weaknesses | join("; ") if entry.weaknesses else "none recorded" }}
{% endfor %}

Tailor the sample answers to directly address these documented patterns:
- For "tell me about yourself" and "why this role", ensure the narrative does not fall into the same traps.
- For "biggest weakness", surface one of the real documented weaknesses above — frame it honestly and show a concrete improvement arc. Do not invent a safe-sounding fake weakness.
- For the behavioural question, pick a scenario that showcases improvement in the documented weak areas.
{% endif %}

Output Markdown. For each question: a `### ` heading with the question, then the answer. No generic disclaimers; no "this is just a template". The candidate should be able to read it back almost verbatim.
```

- [ ] **Step 6: Run smoke tests — expect PASS**

```bash
uv run pytest tests/templates/test_v2_prompts.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/templates/prompts/generate_interview_briefing.v2.txt \
        backend/templates/prompts/mock_interview_question.v2.txt \
        backend/templates/prompts/practice_common_questions.v2.txt \
        tests/templates/__init__.py \
        tests/templates/test_v2_prompts.py
git commit -m "feat: v2 prompt templates with coaching history injection"
```

---

## Task 8: Full Test Run + Restart

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Restart the backend**

```bash
# Kill existing uvicorn and restart (adapt to your local setup)
uv run uvicorn backend.main:app --reload
```

The `lru_cache` is cleared on restart — v2 templates are now live.

- [ ] **Step 3: Verify the DB table was created**

```bash
uv run python -c "
import asyncio, aiosqlite
from backend.storage.db import DB_PATH
async def check():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='coaching_insights'\")
        row = await cur.fetchone()
        print('Table exists:', bool(row))
asyncio.run(check())
"
```

Expected: `Table exists: True`.

---

## End-to-End Verification

**Scenario A — Save path (evaluator):**

1. Start an interview evaluator session with a saved profile (select profile reuse at greeting, so `profile_id` is set).
2. Complete the evaluation flow through to `evaluator_review_node`.
3. Reply `accept` to accept the evaluation.
4. Verify in DB: `SELECT * FROM coaching_insights WHERE profile_id = '<your_profile_id>';` — expect one row with `weaknesses`, `filler_words`, etc. populated.

**Scenario B — Load path (interview prep):**

1. Start an interview prep session with the same profile.
2. Complete greeting with profile reuse.
3. Check state: `GET /api/sessions/{session_id}/state` — `coaching_history` should be a non-empty list.
4. Proceed to briefing generation — the output should contain a `## Coaching Reminders` section referencing the weaknesses from Scenario A.
5. From the interview menu, select `mock` — verify the first question targets a documented weak area.
6. Select `practice` — verify the "biggest weakness" sample answer references a real documented weakness.

**Scenario C — Edge cases:**

- Evaluator session with no profile: accept the evaluation → no crash, `coaching_insights` table unchanged.
- Interview prep session with profile but zero past evaluations: `coaching_history = []` in state, briefing renders without a Coaching Reminders section.

---

## Self-Review

**Spec coverage check:**
- ✅ Save evaluation insights to DB on accept
- ✅ Load coaching history in interview prep on session start
- ✅ Inject into briefing (v2 template)
- ✅ Inject into mock questions (v2 template)
- ✅ Inject into practice answers (v2 template)
- ✅ Profile-scoped (no profile_id = no-op)
- ✅ Append-only (each accepted eval is a distinct row)
- ✅ Prompt versioning (v2 files alongside v1, never edited)
- ✅ StrictUndefined + lru_cache deployment order documented

**No placeholders:** All code is complete and runnable.

**Type consistency:** `coaching_history: list[dict[str, Any]]` in state matches the `list[dict[str, Any]]` return type of `get_coaching_history`. Template iteration uses `entry.weaknesses`, `entry.filler_words`, etc. — all keys match what `get_coaching_history` returns.
