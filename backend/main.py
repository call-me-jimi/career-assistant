"""FastAPI entrypoint for the Personal Application Assistant."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api import routes, uploads, ws
from backend.config import DATA_DIR
from backend.observability.otel import init_otel
from backend.storage.db import init_db

logging.basicConfig(
    level=os.getenv("JOB_APP_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    init_otel()
    yield


app = FastAPI(title="Personal Application Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)
app.include_router(uploads.router)
app.include_router(uploads.voice_router)
app.include_router(ws.router)

# Serve captured job-page screenshots (backend/data/screenshots/*.png).
(DATA_DIR / "screenshots").mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=DATA_DIR), name="media")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
