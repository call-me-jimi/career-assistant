"""Helpers for the agent's interaction with the event bus and human-in-loop.

All agent-side side-effects (emitting chat messages + action events) go
through these helpers so the graph nodes stay short and consistent.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.observability.event_bus import bus

_MESSAGE_NS = uuid.UUID("a8f5f167-0c0a-4c7a-b8b8-2f5f5a5c5e5e")


def _event(session_id: str, payload: dict[str, Any]) -> None:
    bus.publish(session_id, {"timestamp": time.time(), **payload})


def emit_message(
    session_id: str,
    text: str,
    role: str = "assistant",
    *,
    key: str | None = None,
    localized: bool = False,
) -> None:
    """Emit a chat message.

    If `key` is provided, the message_id is derived deterministically from
    `(session_id, key)`. Combined with the event bus's per-session message_id
    set, this means a node containing `interrupt()` can call `emit_message`
    before the interrupt and still only deliver the message once even though
    LangGraph re-executes the node body on resume.

    Set `localized=True` for messages already in the session language (e.g.
    LLM output generated natively in that language) so the WebSocket layer
    skips its translation pass.
    """
    if key is not None:
        message_id = str(uuid.uuid5(_MESSAGE_NS, f"{session_id}:{key}"))
    else:
        message_id = str(uuid.uuid4())
    _event(
        session_id,
        {
            "type": "chat.message",
            "message_id": message_id,
            "role": role,
            "text": text,
            "localized": localized,
        },
    )


def action_start(session_id: str, action: str, label: str) -> str:
    action_id = str(uuid.uuid4())
    _event(
        session_id,
        {
            "type": "action.start",
            "action_id": action_id,
            "action": action,
            "label": label,
        },
    )
    return action_id


def action_finish(session_id: str, action_id: str, status: str = "ok") -> None:
    _event(
        session_id,
        {
            "type": "action.finish",
            "action_id": action_id,
            "status": status,
        },
    )


def emit_state(session_id: str, patch: dict[str, Any]) -> None:
    _event(session_id, {"type": "state.update", "patch": patch})


def emit_export_ready(session_id: str, kind: str, path: str) -> None:
    _event(session_id, {"type": "export.ready", "kind": kind, "path": path})
