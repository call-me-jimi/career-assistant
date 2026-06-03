"""Silently load per-profile coaching history for interview prep sessions."""

from __future__ import annotations

from backend.agent.state import ApplicationState
from backend.storage.coaching_insights import get_coaching_history


async def load_coaching_history_node(state: ApplicationState) -> dict:
    if not state.profile_id:
        return {}
    history = await get_coaching_history(state.profile_id, limit=3)
    return {"coaching_history": history}
