# Setup

Full installation and optional-integration guide. For the 30-second version see the
[README quickstart](../README.md#quickstart).

## Prerequisites

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) — the Python package manager this project uses
- Node.js 18+ and npm
- (Optional) `ffmpeg` system binary — required for the Interview Evaluator and voice input
  (`sudo apt install ffmpeg`)
- (Optional) A Google Cloud service-account JSON for Google Sheets export
- (Optional) A Tavily API key for web-augmented company research
- (Optional) An OTLP-compatible collector (e.g. Phoenix, Jaeger) to ship spans off-process

## Backend

```bash
uv sync
```

`uv sync` installs runtime + dev dependencies (pytest is in the default group). Use `uv run <cmd>`
for everything Python (`uv run uvicorn …`, `uv run pytest`).

Create `.env` at the project root — copy the template and fill it in:

```bash
cp .env.example .env
```

At a minimum set `LLM_PROVIDER`, `LLM_MODEL_NAME`, and `LLM_API_KEY`. See `.env.example` for every
supported variable. API keys are read **only** from `.env` — they are never persisted to
`backend/config/settings.json`. Everything else (default model, per-task overrides, model pricing,
language, currency, export folder) lives in `settings.json` and can be edited from the **Settings**
page in the UI.

Run the backend:

```bash
uv run uvicorn backend.main:app --reload --port 8001
```

For verbose logs (request timing, LLM calls):

```bash
JOB_APP_LOG_LEVEL=DEBUG uv run uvicorn backend.main:app --reload --port 8001
```

Run tests:

```bash
uv run pytest
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:3000` and talks to the backend on `127.0.0.1:8001` via
REST + a WebSocket per session.

## Choosing an LLM provider

Set `LLM_PROVIDER` to one of `anthropic`, `openai`, `ollama`, or `http`. For per-task model
overrides and pricing, see [llm-models.md](llm-models.md). To run fully locally with no cloud
provider, use `ollama` and point `OLLAMA_BASE_URL` at your Ollama server.

## Google Sheets export (optional)

The app appends a row per application to a spreadsheet you own:

1. Create a Google Cloud project and enable the Google Sheets API.
2. Create a service account, generate a JSON key, and store it locally.
3. Share your target spreadsheet with the service-account email (Editor).
4. Set `GOOGLE_SHEETS_SPREADSHEET_ID` and `GOOGLE_SHEETS_CREDENTIALS_PATH` in `.env`.

The app authorises with the `https://www.googleapis.com/auth/spreadsheets` scope via `gspread`.

## Tavily web search (optional)

Tavily provides the live web-search results used by two nodes:

- **`research_company`** — when the extracted company description is thin (< ~200 chars), it queries
  Tavily for company background and asks an LLM to synthesise a 3–5 paragraph profile. Wired into
  the cover-letter and interview-prep graphs.
- **`qa_answer`** — salary questions trigger a Tavily query for market benchmarks before the LLM
  drafts the answer.

Setup:

1. Sign up at [tavily.com](https://tavily.com) and grab an API key (the free tier is plenty for
   development).
2. Add `TAVILY_API_KEY=tvly-...` to `.env`.
3. Restart the backend.

If the key is missing, both nodes degrade gracefully — the assistant skips the web search and works
with whatever context it already has. No code changes needed either way.

## Phoenix tracing (optional)

[Arize Phoenix](https://github.com/Arize-ai/phoenix) is a local LLM-observability UI that ingests
OpenTelemetry spans. With Phoenix running, every `call_llm` shows up as a trace with full prompt,
response, tokens, latency, and session tag — useful when debugging prompts or comparing models.

**You don't need Phoenix to see LLM activity** — the assistant's own right-hand pane already shows
every call per session via the in-process event bus. Phoenix is only worth installing for
cross-session analysis, historical comparison, or OTel-native exploration.

**Recommended: run Phoenix in Docker.** The PyPI packages currently have version mismatches between
`arize-phoenix` and `arize-phoenix-evals` that break `phoenix serve`. Docker avoids the problem —
the image bundles a known-good combination.

```bash
docker run -d --name phoenix \
  -p 6006:6006 -p 4317:4317 \
  -v phoenix-data:/root/.phoenix \
  arizephoenix/phoenix:latest
```

Then add to `.env`:

```bash
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
```

Restart the backend (`init_otel()` reads the env var at startup), trigger one LLM call from the UI,
and open `http://localhost:6006`. Spans are grouped by `session:{id}` — OpenInference's LangChain
instrumentation attaches that tag automatically via `backend/llm/service.py`.

Useful Docker commands:

```bash
docker logs -f phoenix          # watch startup
docker stop phoenix             # pause (data persists in the phoenix-data volume)
docker start phoenix            # resume
docker rm -f phoenix            # remove container (volume survives)
docker volume rm phoenix-data   # wipe all traces
```

If the env var is unset, tracing still runs in-process and feeds the UI cards — nothing is exported
off-process and Phoenix is not required for normal operation.
