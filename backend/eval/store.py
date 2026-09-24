"""Persistence for eval sets, runs and results (tables live in backend/storage/db.py)."""

from __future__ import annotations

import json
import time
from typing import Any

from backend.storage.db import connect

# Stored user prompts are role-labelled by the trace callback ("[human] …").
# Replay only handles single-turn calls: a second role label means chat history.
HUMAN_PREFIX = "[human] "
_TURN_MARKERS = ("\n\n[ai] ", "\n\n[human] ", "\n\n[system] ")


def replayable(user_prompt: str) -> bool:
    return user_prompt.startswith(HUMAN_PREFIX) and not any(m in user_prompt for m in _TURN_MARKERS)


def user_text(user_prompt: str) -> str:
    return user_prompt.removeprefix(HUMAN_PREFIX)


async def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    async with connect() as db:
        cur = await db.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in await cur.fetchall()]


async def pick_traces(
    task: str, last: int, model: str | None = None, one_per_session: bool = True,
    prompt_version: str | None = None,
) -> list[int]:
    """Newest replayable traces of a task; by default the first call of each session,
    so a three-round cover-letter loop contributes one case, not three."""
    rows = await _rows(
        "SELECT trace_id, session_id, user_prompt, model, prompt_version FROM traces "
        "WHERE task=? AND response_text != '' ORDER BY created_at ASC",
        (task,),
    )
    picked: dict[str, int] = {}
    for r in rows:
        if model and model not in (r["model"] or ""):
            continue
        if prompt_version and r["prompt_version"] != prompt_version:
            continue
        if not replayable(r["user_prompt"] or ""):
            continue
        key = r["session_id"] if one_per_session else str(r["trace_id"])
        picked.setdefault(key, r["trace_id"])
    ids = sorted(picked.values(), reverse=True)[:last]
    return sorted(ids)


async def create_set(name: str, task: str, trace_ids: list[int]) -> None:
    async with connect() as db:
        await db.execute(
            "INSERT INTO eval_sets (name, task, trace_ids, created_at) VALUES (?, ?, ?, ?)",
            (name, task, json.dumps(trace_ids), time.time()),
        )
        await db.commit()


async def get_set(name: str) -> dict[str, Any] | None:
    rows = await _rows("SELECT * FROM eval_sets WHERE name=?", (name,))
    if not rows:
        return None
    s = rows[0]
    s["trace_ids"] = json.loads(s["trace_ids"])
    return s


async def list_sets() -> list[dict[str, Any]]:
    rows = await _rows("SELECT * FROM eval_sets ORDER BY created_at DESC")
    for s in rows:
        s["trace_ids"] = json.loads(s["trace_ids"])
    return rows


async def load_cases(trace_ids: list[int]) -> list[dict[str, Any]]:
    if not trace_ids:
        return []
    marks = ",".join("?" * len(trace_ids))
    return await _rows(
        f"SELECT trace_id, session_id, task, provider, model, input_tokens, output_tokens, "
        f"cache_read_tokens, cache_write_tokens, duration_ms, system_prompt, user_prompt, "
        f"response_text, prompt_version FROM traces WHERE trace_id IN ({marks}) ORDER BY trace_id",
        tuple(trace_ids),
    )


async def create_run(
    *,
    set_name: str,
    task: str,
    kind: str,
    baseline_model: str,
    candidate_model: str,
    samples: int,
    judge_model: str | None = None,
) -> int:
    async with connect() as db:
        cur = await db.execute(
            "INSERT INTO eval_runs (set_name, task, kind, baseline_model, candidate_model, "
            "judge_model, samples, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (set_name, task, kind, baseline_model, candidate_model, judge_model, samples, time.time()),
        )
        await db.commit()
        return cur.lastrowid


async def get_run(run_id: int) -> dict[str, Any] | None:
    rows = await _rows("SELECT * FROM eval_runs WHERE run_id=?", (run_id,))
    return rows[0] if rows else None


async def list_runs() -> list[dict[str, Any]]:
    return await _rows("SELECT * FROM eval_runs ORDER BY run_id DESC")


async def set_judge_model(run_id: int, judge_model: str) -> None:
    async with connect() as db:
        await db.execute("UPDATE eval_runs SET judge_model=? WHERE run_id=?", (judge_model, run_id))
        await db.commit()


async def add_result(run_id: int, **fields: Any) -> None:
    fields = {"run_id": run_id, **fields}
    if isinstance(fields.get("metrics"), dict):
        fields["metrics"] = json.dumps(fields["metrics"])
    cols = ", ".join(fields)
    async with connect() as db:
        await db.execute(
            f"INSERT INTO eval_results ({cols}) VALUES ({', '.join('?' * len(fields))})",
            tuple(fields.values()),
        )
        await db.commit()


async def list_results(run_id: int) -> list[dict[str, Any]]:
    rows = await _rows(
        "SELECT * FROM eval_results WHERE run_id=? ORDER BY trace_id, side, variant, sample",
        (run_id,),
    )
    for r in rows:
        r["metrics"] = json.loads(r["metrics"] or "{}")
    return rows


async def update_result(result_id: int, **fields: Any) -> None:
    if isinstance(fields.get("metrics"), dict):
        fields["metrics"] = json.dumps(fields["metrics"])
    sets = ", ".join(f"{k}=?" for k in fields)
    async with connect() as db:
        await db.execute(
            f"UPDATE eval_results SET {sets} WHERE result_id=?", (*fields.values(), result_id)
        )
        await db.commit()
