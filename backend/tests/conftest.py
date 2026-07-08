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
