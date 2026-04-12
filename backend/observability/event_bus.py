"""In-process asyncio pub/sub bus keyed by session_id, with replay log.

Each session has a bounded history of events. When a subscriber attaches,
the existing history is replayed into its queue before new events arrive,
so a client connecting after the runner has already produced events (e.g.
the initial greeting) still sees them.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

HISTORY_LIMIT = 1000


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=HISTORY_LIMIT)
        )
        # message_ids already published per session — used to suppress
        # duplicate chat.message emissions from re-executed interrupt nodes
        # (LangGraph re-runs the entire node body on resume).
        self._seen_message_ids: dict[str, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            for past in self._history.get(session_id, ()):
                queue.put_nowait(past)
            self._subscribers[session_id].add(queue)
        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers[session_id].discard(queue)
            if not self._subscribers[session_id]:
                self._subscribers.pop(session_id, None)

    def publish(self, session_id: str, event: dict[str, Any]) -> None:
        """Publish without awaiting — safe from sync callback contexts."""
        if event.get("type") == "chat.message":
            mid = event.get("message_id")
            seen = self._seen_message_ids[session_id]
            if mid and mid in seen:
                return
            if mid:
                seen.add(mid)
        self._history[session_id].append(event)
        for q in list(self._subscribers.get(session_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def clear(self, session_id: str) -> None:
        self._history.pop(session_id, None)
        self._seen_message_ids.pop(session_id, None)


bus = EventBus()
