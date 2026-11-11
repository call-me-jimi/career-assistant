"""POST /api/translate: quick-reply labels in the session language."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.api.routes as routes
from backend.api.routes import router


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_labels_come_back_translated_in_order(client, monkeypatch):
    async def fake_translate(text, language):
        return f"{language}:{text}"

    monkeypatch.setattr(routes, "translate_label", fake_translate)

    r = await client.post("/api/translate", json={"language": "German", "texts": ["None", "Accept"]})

    assert r.json() == {"translations": ["German:None", "German:Accept"]}


async def test_too_many_labels_are_refused(client):
    r = await client.post("/api/translate", json={"language": "German", "texts": ["x"] * 51})
    assert r.status_code == 422
