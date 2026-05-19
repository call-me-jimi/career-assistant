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
from backend.llm.translate import is_english_language, translate_message
from backend.observability.event_bus import bus
from backend.storage.sessions import get_session

log = logging.getLogger("assistant.ws")

router = APIRouter()


async def _localize_event(event: dict, language: str) -> dict:
    """Translate procedural chat / action text into the session language.

    Messages already flagged `localized` (LLM output generated natively in the
    target language) pass through untouched.
    """
    etype = event.get("type")
    if etype == "chat.message" and not event.get("localized"):
        text = event.get("text")
        if text:
            return {**event, "text": await translate_message(text, language)}
    elif etype == "action.start":
        label = event.get("label")
        if label:
            return {**event, "label": await translate_message(label, language)}
    return event


@router.websocket("/ws/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    runner = registry.get_or_start(session_id)
    session = await get_session(session_id)
    language = (session or {}).get("language") or "English"
    queue = await bus.subscribe(session_id)

    async def pump_events() -> None:
        try:
            while True:
                event = await queue.get()
                if not is_english_language(language):
                    event = await _localize_event(event, language)
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
