"""A failed LLM call pauses the session instead of ending it.

When a node raises (a 529 from Anthropic outlasting the SDK's own retries),
SessionRunner announces a retryable `session.error` and waits. `retry()`
resumes the graph from its last checkpoint: only the failed node runs again,
and an answer the user already gave to an interrupt is not asked for twice.
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


async def test_retry_resumes_the_failed_node_only(monkeypatch):
    calls = {"before": 0, "flaky": 0}

    async def before(state: ApplicationState) -> dict:
        calls["before"] += 1
        return {"phase": "before"}

    async def flaky(state: ApplicationState) -> dict:
        answer = interrupt({"prompt": "motivation?"})
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise RuntimeError("Error code: 529 Overloaded")
        return {"job_title": answer, "phase": "done"}

    def build(checkpointer):
        g = StateGraph(ApplicationState)
        g.add_node("before", before)
        g.add_node("flaky", flaky)
        g.add_edge(START, "before")
        g.add_edge("before", "flaky")
        g.add_edge("flaky", END)
        return g.compile(checkpointer=checkpointer)

    @asynccontextmanager
    async def memory_checkpointer():
        yield MemorySaver()

    async def session_row(_sid):
        return {"assistant_type": "cover_letter", "language": "English"}

    async def noop(*_a, **_k):
        return None

    monkeypatch.setitem(runner_mod.GRAPH_BUILDERS, "cover_letter", build)
    monkeypatch.setattr(runner_mod, "get_checkpointer", memory_checkpointer)
    monkeypatch.setattr(runner_mod, "get_session", session_row)
    monkeypatch.setattr(runner_mod, "touch_session", noop)
    monkeypatch.setattr("backend.agent.interrupts.emit_message", lambda *a, **k: None)

    sid = "retry-test"
    queue = await bus.subscribe(sid)
    events: list[dict] = []

    async def collect() -> None:
        while True:
            events.append(await queue.get())

    collector = asyncio.create_task(collect())
    r = runner_mod.SessionRunner(sid)
    task = asyncio.create_task(r.run())
    try:
        await _until(lambda: any(e["type"] == "interrupt.request" for e in events))
        await r.submit_input("I want to")

        await _until(lambda: any(e["type"] == "session.error" for e in events))
        error = next(e for e in events if e["type"] == "session.error")
        assert error["retryable"] is True
        assert "529" in error["error"]
        assert not r._done

        assert r.retry() is True
        await asyncio.wait_for(task, 2.0)

        assert any(e["type"] == "session.resumed" for e in events)
        assert any(e["type"] == "session.complete" for e in events)
        assert r._final_state["job_title"] == "I want to"
        assert calls == {"before": 1, "flaky": 2}
        # The interrupt was answered once; the retry didn't ask again.
        assert sum(e["type"] == "interrupt.request" for e in events) == 1
    finally:
        collector.cancel()
        task.cancel()
        await bus.unsubscribe(sid, queue)


async def test_retry_is_refused_unless_the_run_failed():
    assert runner_mod.SessionRunner("idle").retry() is False
