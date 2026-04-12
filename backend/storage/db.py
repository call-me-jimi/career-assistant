"""SQLite storage (aiosqlite). Schema init + connection helper."""

from __future__ import annotations

import aiosqlite

from backend.config import DATA_DIR

DB_PATH = DATA_DIR / "assistant.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    cv_text       TEXT NOT NULL,
    candidate_profile TEXT NOT NULL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    applicant_name TEXT,
    phase          TEXT,
    created_at     REAL NOT NULL,
    last_activity  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    trace_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL,
    card_id        TEXT NOT NULL,
    task           TEXT,
    provider       TEXT,
    model          TEXT,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    duration_ms    INTEGER,
    system_prompt  TEXT,
    user_prompt    TEXT,
    response_text  TEXT,
    created_at     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
"""


async def _migrate(db: aiosqlite.Connection) -> None:
    """Add columns introduced after the initial schema."""
    cur = await db.execute("PRAGMA table_info(traces)")
    cols = {row[1] for row in await cur.fetchall()}
    for col in ("system_prompt", "user_prompt", "response_text"):
        if col not in cols:
            await db.execute(f"ALTER TABLE traces ADD COLUMN {col} TEXT")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await _migrate(db)
        await db.commit()


def connect() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH)
