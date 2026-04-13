"""Per-session LangGraph runner.

Drives the compiled graph to its next interrupt, publishes an
`interrupt.request` event, awaits the user's answer from an input queue,
then resumes. Lives as a background asyncio task per session.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.types import Command

from backend.agent.checkpoint import get_checkpointer
from backend.agent.graph import build_graph
from backend.agent.graph_advisor import build_advisor_graph
from backend.agent.graph_interview import build_interview_graph
from backend.agent.state import ApplicationState
from backend.observability.event_bus import bus
from backend.storage.sessions import get_session, touch_session

GRAPH_BUILDERS = {
    "cover_letter": build_graph,
    "interview_prep": build_interview_graph,
    "career_advisor": build_advisor_graph,
}

log = logging.getLogger("assistant.runner")


class SessionRunner:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._input_queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._done = False
        self._graph: Any = None
        self._paused: bool = False

    async def submit_input(self, value: Any) -> None:
        await self._input_queue.put(value)

    def _config(self) -> dict:
        return {"configurable": {"thread_id": self.session_id}, "recursion_limit": 50}

    async def get_state_values(self) -> dict[str, Any] | None:
        if not self._graph:
            return None
        snap = await self._graph.aget_state(self._config())
        values = getattr(snap, "values", None) or {}
        return values if isinstance(values, dict) else dict(values)

    async def update_state_values(self, values: dict[str, Any]) -> bool:
        """Patch the checkpointed state. Only allowed while paused at an interrupt."""
        if not self._graph or not self._paused:
            return False
        await self._graph.aupdate_state(self._config(), values)
        return True

    def _interrupt_from(self, snapshot: Any) -> Any | None:
        """Extract the current interrupt payload from a graph state snapshot."""
        interrupts = getattr(snapshot, "interrupts", None) or getattr(snapshot, "next", None)
        try:
            tasks = getattr(snapshot, "tasks", None) or ()
            for t in tasks:
                t_interrupts = getattr(t, "interrupts", None) or ()
                for it in t_interrupts:
                    val = getattr(it, "value", None)
                    if val is not None:
                        return val
        except Exception:
            pass
        return None

    async def run(self) -> None:
        try:
            session_row = await get_session(self.session_id)
            assistant_type = (session_row or {}).get("assistant_type") or "cover_letter"
            builder = GRAPH_BUILDERS.get(assistant_type, build_graph)

            async with get_checkpointer() as checkpointer:
                graph = builder(checkpointer)
                self._graph = graph
                config = self._config()
                initial = ApplicationState(
                    session_id=self.session_id,
                    assistant_type=assistant_type,  # type: ignore[arg-type]
                ).model_dump()

                next_input: Any = initial
                while True:
                    if isinstance(next_input, Command):
                        result = await graph.ainvoke(next_input, config=config)
                    else:
                        result = await graph.ainvoke(next_input, config=config)

                    snapshot = await graph.aget_state(config)
                    interrupt_value = self._interrupt_from(snapshot)

                    phase = (result or {}).get("phase") if isinstance(result, dict) else None
                    if phase:
                        await touch_session(self.session_id, phase=phase)

                    if interrupt_value is None:
                        # Graph reached END
                        bus.publish(
                            self.session_id,
                            {"type": "session.complete"},
                        )
                        return

                    bus.publish(
                        self.session_id,
                        {"type": "interrupt.request", "payload": interrupt_value},
                    )

                    self._paused = True
                    try:
                        user_value = await self._input_queue.get()
                    finally:
                        self._paused = False
                    next_input = Command(resume=user_value)
        except Exception as exc:  # pragma: no cover
            log.exception("runner failed: %s", exc)
            from backend.agent.interrupts import emit_message
            emit_message(
                self.session_id,
                f"⚠️ The assistant hit an error and had to stop: `{exc}`",
            )
            bus.publish(
                self.session_id,
                {"type": "session.error", "error": str(exc)},
            )
        finally:
            self._done = True
            self._graph = None
            self._paused = False


class RunnerRegistry:
    def __init__(self) -> None:
        self._runners: dict[str, SessionRunner] = {}

    def get_or_start(self, session_id: str) -> SessionRunner:
        runner = self._runners.get(session_id)
        if runner and not runner._done:
            return runner
        runner = SessionRunner(session_id)
        runner._task = asyncio.create_task(runner.run())
        self._runners[session_id] = runner
        return runner

    def get(self, session_id: str) -> SessionRunner | None:
        return self._runners.get(session_id)


registry = RunnerRegistry()
