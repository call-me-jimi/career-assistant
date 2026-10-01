"""POST /sessions/{id}/select-version — a switch on the Details page reaches the chat.

The chat shows the letter cl_review picked. Selecting another version only
patched state, so the chat kept showing the old letter with no sign it had
been replaced.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.agent.state import CoverLetterVersion
from backend.api import routes


class _FakeRunner:
    def __init__(self, values: dict):
        self.values = values

    async def get_state_values(self):
        return self.values

    async def update_state_values(self, patch: dict) -> bool:
        self.values.update(patch)
        return True


@pytest.fixture
def runner(monkeypatch):
    r = _FakeRunner({
        "cover_letter_versions": [
            CoverLetterVersion(version_id="v1", text="Letter one", iteration=1, hm_score=6.0),
            CoverLetterVersion(version_id="v2", text="Letter two", iteration=2, hm_score=8.0),
        ],
        "best_version_id": "v2",
        "cover_letter": "Letter two",
    })
    monkeypatch.setattr(routes.registry, "get", lambda sid: r)
    return r


@pytest.fixture
def messages(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        routes, "emit_message",
        lambda sid, text, role="assistant", **kw: sent.append({"role": role, "text": text, **kw}),
    )
    return sent


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_switching_version_shows_the_new_letter_in_chat(client, runner, messages):
    res = await client.post("/api/sessions/s1/select-version", json={"version_id": "v1"})

    assert res.status_code == 200
    assert runner.values["cover_letter"] == "Letter one"
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "version 1" in messages[0]["text"]
    assert messages[1]["text"] == "Letter one"
    assert messages[1]["localized"] is True


async def test_reselecting_the_current_version_says_nothing(client, runner, messages):
    res = await client.post("/api/sessions/s1/select-version", json={"version_id": "v2"})

    assert res.status_code == 200
    assert messages == []
