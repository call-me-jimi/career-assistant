"""Async SQLite checkpointer for LangGraph."""

from __future__ import annotations

from contextlib import asynccontextmanager

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.config import DATA_DIR

CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"


@asynccontextmanager
async def get_checkpointer():
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        yield saver
