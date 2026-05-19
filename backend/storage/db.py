"""SQLite storage (aiosqlite). Schema init + connection helper."""

from __future__ import annotations

import aiosqlite

from backend.config import DATA_DIR

DB_PATH = DATA_DIR / "assistant.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    applicant_name  TEXT,
    cv_text         TEXT NOT NULL,
    candidate_profile TEXT NOT NULL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    applicant_name TEXT,
    phase          TEXT,
    assistant_type TEXT NOT NULL DEFAULT 'cover_letter',
    language       TEXT NOT NULL DEFAULT 'English',
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

CREATE TABLE IF NOT EXISTS application_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id          TEXT NOT NULL,
    session_id          TEXT NOT NULL,
    job_title           TEXT,
    company_name        TEXT,
    job_source_type     TEXT,
    initial_cl          TEXT,
    final_cl            TEXT,
    revision_count      INTEGER NOT NULL DEFAULT 0,
    hm_feedback_final   TEXT,
    revision_feedback   TEXT,
    created_at          REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_application_records_profile
    ON application_records(profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS application_hm_iterations (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    application_record_id  INTEGER NOT NULL,
    iteration              INTEGER NOT NULL,
    score                  REAL,
    strengths              TEXT,
    weaknesses             TEXT,
    suggestions            TEXT,
    FOREIGN KEY (application_record_id) REFERENCES application_records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_application_hm_iterations_record
    ON application_hm_iterations(application_record_id);

CREATE TABLE IF NOT EXISTS profile_playbook (
    profile_id               TEXT PRIMARY KEY,
    never_say                TEXT NOT NULL DEFAULT '[]',
    prefer_phrasing          TEXT NOT NULL DEFAULT '[]',
    recurring_hm_weaknesses  TEXT NOT NULL DEFAULT '[]',
    tone_notes               TEXT NOT NULL DEFAULT '',
    updated_at               REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_suggestions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id              TEXT NOT NULL,
    kind                    TEXT NOT NULL DEFAULT 'candidate_profile_edit',
    diff                    TEXT NOT NULL,
    confidence              INTEGER NOT NULL DEFAULT 1,
    status                  TEXT NOT NULL DEFAULT 'pending',
    source_application_ids  TEXT NOT NULL DEFAULT '[]',
    created_at              REAL NOT NULL,
    resolved_at             REAL
);

CREATE INDEX IF NOT EXISTS idx_profile_suggestions_profile_status
    ON profile_suggestions(profile_id, status);
"""


async def _migrate(db: aiosqlite.Connection) -> None:
    """Add columns introduced after the initial schema."""
    cur = await db.execute("PRAGMA table_info(traces)")
    cols = {row[1] for row in await cur.fetchall()}
    for col in ("system_prompt", "user_prompt", "response_text"):
        if col not in cols:
            await db.execute(f"ALTER TABLE traces ADD COLUMN {col} TEXT")

    cur = await db.execute("PRAGMA table_info(sessions)")
    session_cols = {row[1] for row in await cur.fetchall()}
    if "assistant_type" not in session_cols:
        await db.execute(
            "ALTER TABLE sessions ADD COLUMN assistant_type TEXT NOT NULL DEFAULT 'cover_letter'"
        )
    if "language" not in session_cols:
        await db.execute(
            "ALTER TABLE sessions ADD COLUMN language TEXT NOT NULL DEFAULT 'English'"
        )

    cur = await db.execute("PRAGMA table_info(profiles)")
    profile_cols = {row[1] for row in await cur.fetchall()}
    if "applicant_name" not in profile_cols:
        await db.execute("ALTER TABLE profiles ADD COLUMN applicant_name TEXT")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await _migrate(db)
        await db.commit()


def connect() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH)
