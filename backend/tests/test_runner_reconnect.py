"""Reopening a session after a backend restart picks up its checkpoint instead of restarting it.

The event bus keeps history in memory only, so after a restart the next WebSocket connect builds a
fresh SessionRunner for a thread that already has checkpoints. Invoking the graph with the initial
state again would start a new run on top of them: a finished session would fall back to the
greeting, and a paused one would lose every answer already given.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.agent import runner as runner_mod
from backend.agent.state import ApplicationState
from backend.observability.event_bus import bus


async def _until(predicate, timeout: float = 2.0) -> None:
    async def wait() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout)


def _setup(monkeypatch, saver: MemorySaver, calls: dict) -> None:
    async def first(state: ApplicationState) -> dict:
        calls["first"] += 1
        return {"phase": "asked"}

    async def ask(state: ApplicationState) -> dict:
        answer = interrupt({"prompt": "job title?"})
        calls["ask"] += 1
        return {
            "job_title": answer,
            "interview_evaluation": {"overall_score": 7.0},
            "phase": "done",
        }

    def build(checkpointer):
        g = StateGraph(ApplicationState)
        g.add_node("first", first)
        g.add_node("ask", ask)
        g.add_edge(START, "first")
        g.add_edge("first", "ask")
        g.add_edge("ask", END)
        return g.compile(checkpointer=checkpointer)

    @asynccontextmanager
    async def checkpointer():
        yield saver  # shared across runners, like the SQLite file across restarts

    async def session_row(_sid):
        return {"assistant_type": "cover_letter", "language": "German"}

    async def noop(*_a, **_k):
        return None

    monkeypatch.setitem(runner_mod.GRAPH_BUILDERS, "cover_letter", build)
    monkeypatch.setattr(runner_mod, "get_checkpointer", checkpointer)
    monkeypatch.setattr(runner_mod, "get_session", session_row)
    monkeypatch.setattr(runner_mod, "touch_session", noop)
    monkeypatch.setattr("backend.agent.interrupts.emit_message", lambda *a, **k: None)


async def _run_with_events(sid: str, body) -> list[dict]:
    """Run a fresh SessionRunner (a new backend process) and collect what it publishes."""
    bus.clear(sid)  # a restart starts with an empty event history
    queue = await bus.subscribe(sid)
    events: list[dict] = []

    async def collect() -> None:
        while True:
            events.append(await queue.get())

    collector = asyncio.create_task(collect())
    r = runner_mod.SessionRunner(sid)
    task = asyncio.create_task(r.run())
    try:
        await body(r, task, events)
    finally:
        collector.cancel()
        task.cancel()
        await bus.unsubscribe(sid, queue)
    return events


async def test_finished_session_is_not_restarted(monkeypatch):
    calls = {"first": 0, "ask": 0}
    saver = MemorySaver()
    _setup(monkeypatch, saver, calls)
    sid = "reconnect-finished"

    async def finish(r, task, events):
        await _until(lambda: any(e["type"] == "interrupt.request" for e in events))
        await r.submit_input("Head of Data")
        await asyncio.wait_for(task, 2.0)

    await _run_with_events(sid, finish)
    assert calls == {"first": 1, "ask": 1}

    async def reopen(r, task, events):
        await asyncio.wait_for(task, 2.0)
        assert r._final_state["job_title"] == "Head of Data"
        assert r._final_state["phase"] == "done"

    events = await _run_with_events(sid, reopen)
    assert calls == {"first": 1, "ask": 1}  # no node ran again
    assert not any(e["type"] == "interrupt.request" for e in events)
    assert events[-1] == {"type": "session.complete"}
    # What the live run streamed as state comes back, so the report shows again.
    restored = next(e for e in events if e["type"] == "state.update")
    assert restored["patch"] == {"language": "German", "interview_evaluation": {"overall_score": 7.0}}


async def test_paused_session_resumes_at_its_question(monkeypatch):
    calls = {"first": 0, "ask": 0}
    saver = MemorySaver()
    _setup(monkeypatch, saver, calls)
    sid = "reconnect-paused"

    async def pause(r, task, events):
        await _until(lambda: any(e["type"] == "interrupt.request" for e in events))

    await _run_with_events(sid, pause)  # the backend stops while the question is open
    assert calls == {"first": 1, "ask": 0}

    async def answer(r, task, events):
        await _until(lambda: any(e["type"] == "interrupt.request" for e in events))
        await r.submit_input("Head of AI")
        await asyncio.wait_for(task, 2.0)
        assert r._final_state["job_title"] == "Head of AI"

    events = await _run_with_events(sid, answer)
    assert calls == {"first": 1, "ask": 1}  # "first" did not run again
    assert sum(e["type"] == "interrupt.request" for e in events) == 1
