import aiosqlite
import pytest

import backend.storage.db as db_module
from backend.storage.db import SCHEMA, _migrate


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """Temp SQLite DB with full schema; patches DB_PATH for the duration."""
    path = tmp_path / "test.sqlite"
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await _migrate(db)
        await db.commit()
    monkeypatch.setattr(db_module, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def relearned(monkeypatch):
    """Profiles the api asked to learn from employers again. Recorded, never run: a
    test that records a reply must not reach a real model in the background."""
    calls: list[str] = []
    import backend.api.routes as routes

    monkeypatch.setattr(routes, "schedule_employer_learning", calls.append)
    return calls
