"""WebSocket stream for a single session.

Protocol:
- Server → client: events from the event bus (chat.message, action.*, llm.*,
  interrupt.request, state.update, export.ready, session.complete).
- Client → server: JSON `{"type": "user.input", "value": <any>}` to resume
  the graph at the current interrupt.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.agent.runner import registry
from backend.observability.event_bus import bus

log = logging.getLogger("assistant.ws")

router = APIRouter()


@router.websocket("/ws/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    runner = registry.get_or_start(session_id)
    queue = await bus.subscribe(session_id)

    async def pump_events() -> None:
        try:
            while True:
                event = await queue.get()
                await websocket.send_text(json.dumps(event, default=str))
        except Exception:  # pragma: no cover
            pass

    pump_task = asyncio.create_task(pump_events())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "user.input":
                await runner.submit_input(msg.get("value"))
    except WebSocketDisconnect:
        log.info("ws disconnect session=%s", session_id)
    finally:
        pump_task.cancel()
        await bus.unsubscribe(session_id, queue)
