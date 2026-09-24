# Backend: FastAPI + LangGraph on :8001.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

ARG UID=1000
ARG GID=1000
# `true` pulls torch (~2.5GB) for speaker diarization on interview transcripts.
ARG WITH_DIARIZATION=false

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HF_HOME=/home/app/.cache/huggingface \
    PYTHONUNBUFFERED=1

# WeasyPrint (PDF export) needs Pango; fonts so letters don't render in a fallback face.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g ${GID} app && useradd -m -u ${UID} -g ${GID} app

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$WITH_DIARIZATION" = "true" ]; then EXTRA="--extra diarization"; fi; \
    uv sync --locked --no-dev --no-install-project $EXTRA

# Job-page screenshots on scrape; not covered by `uv sync`.
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright

COPY backend ./backend

RUN mkdir -p backend/data /exports "$HF_HOME" \
    && chown -R app:app backend/data backend/config /exports /home/app/.cache

USER app
EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
