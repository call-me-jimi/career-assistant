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
    employer_feedback_themes TEXT NOT NULL DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS coaching_insights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id    TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    journey_id    TEXT,
    interview_id  TEXT,
    job_title     TEXT NOT NULL DEFAULT '',
    company_name  TEXT NOT NULL DEFAULT '',
    overall_score REAL,
    decision      TEXT,
    summary       TEXT NOT NULL DEFAULT '',
    weaknesses    TEXT NOT NULL DEFAULT '[]',
    improvements  TEXT NOT NULL DEFAULT '[]',
    filler_words  TEXT NOT NULL DEFAULT '[]',
    pace          TEXT,
    clarity       TEXT,
    created_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coaching_insights_profile
    ON coaching_insights(profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS job_journeys (
    journey_id            TEXT PRIMARY KEY,
    profile_id            TEXT,
    job_url               TEXT NOT NULL DEFAULT '',
    job_title             TEXT NOT NULL DEFAULT '',
    company_name          TEXT NOT NULL DEFAULT '',
    location              TEXT NOT NULL DEFAULT '',
    job_description       TEXT NOT NULL DEFAULT '',
    company_description   TEXT NOT NULL DEFAULT '',
    job_ad_language       TEXT NOT NULL DEFAULT '',
    job_screenshot_path   TEXT NOT NULL DEFAULT '',
    job_source_type       TEXT NOT NULL DEFAULT '',
    alignment_strategy    TEXT NOT NULL DEFAULT '',
    inferred_role_context TEXT NOT NULL DEFAULT '',
    positioning_strategy  TEXT NOT NULL DEFAULT '',
    cover_letter          TEXT NOT NULL DEFAULT '',
    interview_briefing    TEXT NOT NULL DEFAULT '',
    evaluation_summary    TEXT NOT NULL DEFAULT '',
    export_folder         TEXT NOT NULL DEFAULT '',
    cover_letter_at       REAL,
    interview_briefing_at REAL,
    evaluation_summary_at REAL,
    applied_at            REAL,
    on_hold_at            REAL,
    rejected_at           REAL,
    dropped_at            REAL,
    offer_at              REAL,
    notes                 TEXT NOT NULL DEFAULT '',
    next_step             TEXT NOT NULL DEFAULT '',
    next_step_at          REAL,
    created_at            REAL NOT NULL,
    updated_at            REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_journeys_profile
    ON job_journeys(profile_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS job_interviews (
    interview_id       TEXT PRIMARY KEY,
    journey_id         TEXT NOT NULL,
    profile_id         TEXT,
    interview_type     TEXT NOT NULL DEFAULT 'other',
    label              TEXT NOT NULL DEFAULT '',
    context            TEXT NOT NULL DEFAULT '',
    briefing           TEXT NOT NULL DEFAULT '',
    evaluation_summary TEXT NOT NULL DEFAULT '',
    briefing_at        REAL,
    evaluation_at      REAL,
    scheduled_at       REAL,
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL,
    FOREIGN KEY (journey_id) REFERENCES job_journeys(journey_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_interviews_journey
    ON job_interviews(journey_id, created_at);

CREATE TABLE IF NOT EXISTS job_feedback (
    feedback_id   TEXT PRIMARY KEY,
    journey_id    TEXT NOT NULL,
    profile_id    TEXT,
    interview_ids TEXT NOT NULL DEFAULT '[]',
    stage         TEXT NOT NULL DEFAULT 'unknown',
    outcome       TEXT NOT NULL DEFAULT 'rejected',
    source        TEXT NOT NULL DEFAULT '',
    feedback_text TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    FOREIGN KEY (journey_id) REFERENCES job_journeys(journey_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_feedback_journey
    ON job_feedback(journey_id, created_at);

CREATE INDEX IF NOT EXISTS idx_job_feedback_profile
    ON job_feedback(profile_id, created_at DESC);

-- The application tracker's event log: a follow-up sent, a recruiter who called.
-- Deliberately never consulted when deriving a job's status — only dates do that.
CREATE TABLE IF NOT EXISTS job_events (
    event_id    TEXT PRIMARY KEY,
    journey_id  TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'note',
    occurred_at REAL NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    FOREIGN KEY (journey_id) REFERENCES job_journeys(journey_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_events_journey
    ON job_events(journey_id, occurred_at DESC);
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

    # Themes distilled from what employers actually said, kept apart from the
    # simulator's recurring_hm_weaknesses so real and simulated signal stay distinct.
    cur = await db.execute("PRAGMA table_info(profile_playbook)")
    playbook_cols = {row[1] for row in await cur.fetchall()}
    if "employer_feedback_themes" not in playbook_cols:
        await db.execute(
            "ALTER TABLE profile_playbook "
            "ADD COLUMN employer_feedback_themes TEXT NOT NULL DEFAULT '[]'"
        )

    # Which job and which round an evaluation belongs to. Without these an evaluation
    # cannot be paired with the employer feedback that covers it (see job_feedback).
    # Rows written before this stay NULL and are skipped by the pairing query.
    cur = await db.execute("PRAGMA table_info(coaching_insights)")
    coaching_cols = {row[1] for row in await cur.fetchall()}
    for col in ("journey_id", "interview_id"):
        if col not in coaching_cols:
            await db.execute(f"ALTER TABLE coaching_insights ADD COLUMN {col} TEXT")

    cur = await db.execute("PRAGMA table_info(job_journeys)")
    journey_cols = {row[1] for row in await cur.fetchall()}
    for col in ("cover_letter_at", "interview_briefing_at", "evaluation_summary_at"):
        if col not in journey_cols:
            await db.execute(f"ALTER TABLE job_journeys ADD COLUMN {col} REAL")
    if "job_screenshot_path" not in journey_cols:
        await db.execute(
            "ALTER TABLE job_journeys ADD COLUMN job_screenshot_path TEXT NOT NULL DEFAULT ''"
        )
    if "export_folder" not in journey_cols:
        # Where this job's artifacts were first exported, so later sessions
        # (prep, evaluator) write into the same folder instead of a new
        # today-dated one. Empty for journeys created before this column.
        await db.execute(
            "ALTER TABLE job_journeys ADD COLUMN export_folder TEXT NOT NULL DEFAULT ''"
        )

    # The application tracker's dates. Status is never stored — derive_status()
    # in journeys.py reads these five plus job_interviews.scheduled_at, so a
    # status can never drift from the dates that define it.
    for col in ("applied_at", "on_hold_at", "rejected_at", "dropped_at", "offer_at",
                "next_step_at"):
        if col not in journey_cols:
            await db.execute(f"ALTER TABLE job_journeys ADD COLUMN {col} REAL")
    for col in ("notes", "next_step"):
        if col not in journey_cols:
            await db.execute(
                f"ALTER TABLE job_journeys ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
            )

    # When the round actually happened, as opposed to when a graph created the row.
    cur = await db.execute("PRAGMA table_info(job_interviews)")
    interview_cols = {row[1] for row in await cur.fetchall()}
    if "scheduled_at" not in interview_cols:
        await db.execute("ALTER TABLE job_interviews ADD COLUMN scheduled_at REAL")

    # Backfill job_journeys from the latest application_records row per
    # (profile, company, title). Idempotent — NOT EXISTS makes reruns no-ops.
    await db.execute(
        """
        INSERT INTO job_journeys (journey_id, profile_id, job_title, company_name,
            job_source_type, cover_letter, created_at, updated_at)
        SELECT lower(hex(randomblob(16))), ar.profile_id, ar.job_title, ar.company_name,
            ar.job_source_type, COALESCE(ar.final_cl, ''), ar.created_at, ar.created_at
        FROM application_records ar
        WHERE COALESCE(ar.company_name, '') != ''
          AND ar.id = (SELECT MAX(ar2.id) FROM application_records ar2
                       WHERE ar2.profile_id = ar.profile_id
                         AND lower(COALESCE(ar2.company_name,'')) = lower(ar.company_name)
                         AND lower(COALESCE(ar2.job_title,''))   = lower(COALESCE(ar.job_title,'')))
          AND NOT EXISTS (SELECT 1 FROM job_journeys j
                          WHERE COALESCE(j.profile_id,'') = COALESCE(ar.profile_id,'')
                            AND lower(j.company_name) = lower(ar.company_name)
                            AND lower(j.job_title)    = lower(COALESCE(ar.job_title,'')))
        """
    )

    # Journeys written before artifact timestamps existed (or just backfilled
    # above) recorded their cover letter at journey creation time. Idempotent.
    await db.execute(
        """
        UPDATE job_journeys SET cover_letter_at = created_at
        WHERE cover_letter != '' AND cover_letter_at IS NULL
        """
    )

    # Briefings written before per-round tracking existed belong to some round we
    # can no longer identify — file them as one 'other' round so the interview
    # picker can still offer them. Idempotent: skipped once a journey has rounds.
    await db.execute(
        """
        INSERT INTO job_interviews (interview_id, journey_id, profile_id, interview_type,
            label, briefing, briefing_at, created_at, updated_at)
        SELECT lower(hex(randomblob(16))), j.journey_id, j.profile_id, 'other',
            'Earlier round', j.interview_briefing,
            COALESCE(j.interview_briefing_at, j.updated_at),
            COALESCE(j.interview_briefing_at, j.created_at), j.updated_at
        FROM job_journeys j
        WHERE j.interview_briefing != ''
          AND NOT EXISTS (SELECT 1 FROM job_interviews i WHERE i.journey_id = j.journey_id)
        """
    )

    # --- Tracker backfill. Every statement is WHERE ... IS NULL, so reruns are
    # no-ops and a date the user corrected by hand is never overwritten.

    # A journey exists because an assistant was run on that job, so treat it as
    # applied. The cover letter's timestamp is the closest thing to a send date.
    await db.execute(
        """
        UPDATE job_journeys SET applied_at = COALESCE(cover_letter_at, created_at)
        WHERE applied_at IS NULL
        """
    )

    await db.execute(
        "UPDATE job_interviews SET scheduled_at = created_at WHERE scheduled_at IS NULL"
    )

    # An employer's verdict already sits in job_feedback — move it onto the date
    # column that derive_status() reads. 'ghosted' maps to nothing on purpose:
    # no response is not an outcome date, so those rows stay Applied.
    for outcome, column in (
        ("rejected", "rejected_at"),
        ("offer", "offer_at"),
        ("withdrawn", "dropped_at"),
    ):
        await db.execute(
            f"""
            UPDATE job_journeys SET {column} = (
                SELECT MAX(f.created_at) FROM job_feedback f
                WHERE f.journey_id = job_journeys.journey_id AND f.outcome = ?
            )
            WHERE {column} IS NULL
              AND EXISTS (
                SELECT 1 FROM job_feedback f
                WHERE f.journey_id = job_journeys.journey_id AND f.outcome = ?
              )
            """,
            (outcome, outcome),
        )


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await _migrate(db)
        await db.commit()


def connect() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH)
