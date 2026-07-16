"""Async SQLite checkpointer for LangGraph."""

from __future__ import annotations

from contextlib import asynccontextmanager

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.agent.state import (
    ApplicationState,
    ChatTurn,
    CoverLetterVersion,
    ExportResult,
    QAItem,
)
from backend.config import DATA_DIR

CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"

# Custom types the checkpointer serializes via msgpack. Registering them in the
# allowlist silences the "Deserializing unregistered type" warning and keeps
# checkpoints loadable once LangGraph blocks unregistered types by default.
_ALLOWED_MSGPACK_MODULES = [
    ApplicationState,
    CoverLetterVersion,
    QAItem,
    ChatTurn,
    ExportResult,
]


@asynccontextmanager
async def get_checkpointer():
    serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
    async with aiosqlite.connect(str(CHECKPOINT_DB)) as conn:
        yield AsyncSqliteSaver(conn, serde=serde)
