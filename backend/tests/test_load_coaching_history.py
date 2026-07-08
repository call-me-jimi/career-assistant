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
