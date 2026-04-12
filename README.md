# Personal Application Assistant

An agentic, conversational helper that walks you end-to-end through a job application: ingest your CV, scrape and analyse a job posting, build a positioning strategy, draft and iteratively refine a tailored cover letter (with a hiring-manager-feedback loop), answer common application questions, and export the result. Built on **LangGraph** with a human-in-the-loop interrupt model, multi-provider LLM support, OpenTelemetry-based tracing, and a Next.js + Tailwind chat UI.

This is a sibling of the legacy `app/` project. Where `app/` is a multi-screen wizard, the assistant is a single conversation: one chat thread driven by a state graph that pauses for input whenever it needs you.

## Features

- **Conversational, single-thread UX**: One chat replaces the wizard. The graph pauses at human-in-the-loop interrupts and resumes when you reply.
- **CV intake and profile extraction**: Upload a PDF; the agent parses it and produces a structured candidate profile reused throughout the session.
- **Job ingestion**: Paste a URL (scraped via `requests` + BeautifulSoup) or raw text. An LLM extraction step fills `job_title`, `company_name`, `job_description`, `company_description`, and `location`.
- **Direct vs. recruiter flows**: The agent classifies the posting as a company ad (`direct`) or agency posting (`recruiter`) and routes through `alignment_strategy` or `infer_role` + `position_candidate` accordingly.
- **Company research**: Optional Tavily web search enriches the company description.
- **Cover-letter loop with HM feedback**: Generates a draft, runs a `simulate_hiring_manager` critique pass, and iterates up to `max_hm_iterations` (default 3) or until `quality_threshold` is met. All versions are kept (`cover_letter_versions`) and you can pick the winner.
- **Q&A module**: Predefined questions (motivation, salary, experience) plus custom questions, each answered with the same context the cover letter saw.
- **Multi-format export**: PDF (WeasyPrint), Markdown, JSON, and Google Sheets append.
- **Multi-provider LLM service**: Anthropic, OpenAI, Ollama, or a generic HTTP endpoint. Each task can override the default model/provider.
- **Per-session observability**: OpenTelemetry tracer + OpenInference LangChain instrumentation feed an in-process event bus. The UI shows live LLM "cards" (prompt, response, tokens, USD cost) for every call in the session.
- **Persistent state**: SQLite (via `aiosqlite`) stores sessions, profiles, and full LLM traces. LangGraph checkpoints make every node resumable.

## Quickstart

```bash
# Backend
uv sync
cp .env.example .env              # then fill in at minimum LLM_PROVIDER + LLM_API_KEY
uv run uvicorn backend.main:app --reload --port 8001
```

```bash
# Frontend
cd frontend
npm install
npm run dev                       # http://localhost:3000
```

Open `http://localhost:3000`, click **New session**, and start chatting. The backend runs on `http://127.0.0.1:8001` and the WebSocket stream is exposed at `ws://127.0.0.1:8001/ws/{session_id}`.

## Setup

### Prerequisites

- Python 3.12+
- `uv` — install from https://github.com/astral-sh/uv
- Node.js 18+ and npm
- (Optional) Google Cloud service account JSON for Google Sheets export
- (Optional) Tavily API key for web-augmented company research
- (Optional) An OTLP-compatible collector (e.g. Phoenix, Jaeger) if you want to ship spans off-process

### Backend

```bash
uv sync
```

`uv sync` installs runtime + dev dependencies (pytest is in the default group). Use `uv run <cmd>` for everything Python (`uv run uvicorn …`, `uv run pytest`).

Create `.env` at the project root with at least:

```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL_NAME=claude-sonnet-4-5

# Optional, provider-specific
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434
LLM_BASE_URL=

# Optional integrations
TAVILY_API_KEY=tvly-...
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_SHEETS_CREDENTIALS_PATH=/absolute/path/to/service_account.json

# Output / runtime
DEFAULT_EXPORT_FOLDER=~/JobApplications/Applications
PHOENIX_COLLECTOR_ENDPOINT=
JOB_APP_LOG_LEVEL=INFO
```

API keys are read **only** from `.env` — they are never persisted to `backend/config/settings.json`. Everything else (default model, per-task overrides, model pricing, language, currency) lives in `settings.json` and can be edited from the **Settings** page in the UI.

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

### Google Sheets export (optional)

The legacy `app/` README has a step-by-step walkthrough; the assistant uses the **same** pattern:

1. Create a Google Cloud project and enable the Google Sheets API.
2. Create a service account, generate a JSON key, and store it locally.
3. Share your target spreadsheet with the service account email (Editor).
4. Set `GOOGLE_SHEETS_SPREADSHEET_ID` and `GOOGLE_SHEETS_CREDENTIALS_PATH` in `.env`.

The app authorises with the `https://www.googleapis.com/auth/spreadsheets` scope via `gspread`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:3000` and talks to the backend on `127.0.0.1:8001` via REST + a WebSocket per session.

## Architecture

```
assistant/
├── backend/
│   ├── agent/              # LangGraph StateGraph
│   │   ├── graph.py        # node + edge wiring
│   │   ├── state.py        # ApplicationState (pydantic)
│   │   ├── runner.py       # per-session runner (drives graph to next interrupt)
│   │   ├── interrupts.py   # human-in-loop interrupt helpers
│   │   ├── checkpoint.py   # SQLite checkpointer factory
│   │   └── nodes/          # one file per node (greeting, cv_intake, …)
│   ├── api/
│   │   ├── routes.py       # REST: sessions, state, traces, settings, mermaid
│   │   ├── uploads.py      # CV PDF upload
│   │   └── ws.py           # /ws/{session_id} stream
│   ├── llm/
│   │   ├── service.py      # multi-provider dispatch
│   │   ├── prompts.py      # Jinja2 template resolution (latest vN wins)
│   │   └── schemas.py      # task-specific response schemas
│   ├── observability/
│   │   ├── otel.py         # OTel tracer + OpenInference LangChain instrumentation
│   │   ├── callbacks.py    # LangChain callback → trace storage + event bus
│   │   └── event_bus.py    # in-process per-session pub/sub
│   ├── storage/
│   │   ├── db.py           # aiosqlite init
│   │   ├── sessions.py     # session lifecycle
│   │   ├── profiles.py     # reusable applicant profiles
│   │   └── traces.py       # LLM call traces (input/output, tokens)
│   ├── tools/
│   │   ├── scraper.py      # job-page fetch + parse
│   │   ├── cv_parser.py    # PDF → text (pypdf)
│   │   ├── exporters.py    # PDF / md / JSON / Google Sheets
│   │   └── web_search.py   # Tavily wrapper
│   ├── templates/
│   │   ├── prompts/        # user prompts, versioned as {stem}.vN.txt
│   │   └── system/         # matching system prompts
│   ├── config/settings.json  # runtime LLM + pricing + locale (no secrets)
│   ├── config.py           # .env + settings.json loader
│   └── main.py             # FastAPI app (lifespan: init_db + init_otel)
├── frontend/               # Next.js 14 App Router + Tailwind
│   ├── app/
│   │   ├── page.tsx        # landing / new session
│   │   ├── session/
│   │   │   ├── page.tsx        # 2/3 chat + 1/3 LLM cards layout
│   │   │   ├── details/        # editable session-state inspector
│   │   │   ├── graph/          # live Mermaid view of the LangGraph
│   │   │   └── usage/          # per-call tokens + USD cost
│   │   └── settings/page.tsx   # default + per-task LLM, model pricing
│   ├── components/         # ChatPane, InputBar, LLMCardPane
│   └── lib/                # API + WS clients
├── main.py                 # convenience entrypoint
├── pyproject.toml
└── uv.lock
```

### State graph

`backend/agent/graph.py` wires a linear pipeline with a Q&A loop and an export branch:

```
START → greeting → cv_intake → collect_job → extract_info → fill_missing_info
      → confirm_info → research_company → classify_flow → strategy
      → cl_loop → cl_review → qa_menu ⇄ qa_answer → export → (qa_menu | END)
```

- **`cl_loop`** runs `cover_letter_generation` and `simulate_hiring_manager` up to `max_hm_iterations` (default 3) or until `hm_score >= quality_threshold` (default 8.5). Each iteration produces a `CoverLetterVersion` (`version_id`, `text`, `iteration`, `hm_score`, `hm_feedback`).
- **`cl_review`** lets you pick the best version (`POST /api/sessions/{id}/select-version`) before moving on.
- **`qa_menu` / `qa_answer`** form a loop so you can ask multiple predefined or custom questions before exporting.
- **`export_node`** appends to Google Sheets and writes PDF / md / JSON to `DEFAULT_EXPORT_FOLDER`.

The full state lives in `backend/agent/state.py` (`ApplicationState`): applicant fields, job/company fields, strategy text, the `cover_letter_versions` list, `qa_items`, and `export_results`. Any non-`None` field on a node return is merged into the checkpointed state by LangGraph.

### Session runner and human-in-the-loop

`backend/agent/runner.py` (`SessionRunner`) drives one compiled graph per session as a background asyncio task. It:

1. Streams the graph forward until it hits an interrupt (or finishes).
2. Publishes an `interrupt.request` event on the per-session event bus.
3. Awaits the next message from its input queue (fed by the WebSocket).
4. Resumes the graph with `Command(resume=…)`.

While paused, REST clients may patch editable state fields via `PATCH /api/sessions/{id}/state` (whitelist in `routes.py:EDITABLE_FIELDS`). Updates while the runner is *not* paused return 409.

### LLM service and prompt versioning

`backend/llm/service.py` dispatches to Anthropic, OpenAI, Ollama, or a generic HTTP endpoint based on the resolved `LLMConfig`. Each task in `KNOWN_TASKS` (see `backend/config.py`) may override the default model/provider via `task_llm_configs` in `settings.json`, edited from the **Settings** page.

Prompts are versioned files under `backend/templates/prompts/{stem}.vN.txt` and `backend/templates/system/{stem}.system.vN.txt`. Resolution always picks the **highest `vN`** on disk — add a new version by creating a new file, never by editing an existing one.

### Observability

`init_otel()` (called in the FastAPI lifespan) configures an OpenTelemetry tracer and installs **OpenInference** LangChain instrumentation. Each LLM call:

1. Emits OTel spans (optionally exported to `PHOENIX_COLLECTOR_ENDPOINT`).
2. Goes through a LangChain callback that persists a trace row (`backend/storage/traces.py`) with prompt, response, model, input/output tokens, and timing.
3. Publishes an `llm.*` event on the per-session event bus, which the WebSocket forwards to the UI.

The UI's right-hand pane lists every call as a card; clicking one opens the full prompt/response view. USD cost is computed on the fly from `model_pricing` in settings, so adding a new model only requires a pricing entry.

### Storage

SQLite via `aiosqlite` (`backend/storage/db.py`). Three tables:

- **sessions** — id, phase, timestamps.
- **profiles** — reusable applicant profiles (CV text + extracted profile).
- **traces** — every LLM call ever made in the session (input/output, tokens, model, timing).

LangGraph checkpoints live in their own SQLite file (`backend/agent/checkpoint.py`) so a graph can be resumed across process restarts.

### Frontend

Next.js 14 App Router with Tailwind. Layout is **2/3 chat + 1/3 LLM cards**:

- `app/session/page.tsx` — main chat. Subscribes to `/ws/{session_id}`, renders `chat.message` events in `ChatPane`, and posts `user.input` messages from `InputBar`.
- `app/session/details/page.tsx` — inspect / edit the session state (only while the runner is paused at an interrupt).
- `app/session/graph/page.tsx` — renders the live Mermaid topology fetched from `GET /api/graph/mermaid`.
- `app/session/usage/page.tsx` — per-call tokens + USD cost.
- `app/settings/page.tsx` — default LLM, per-task overrides, model pricing.

## REST + WebSocket API

Main routes (see `backend/api/routes.py`, `backend/api/ws.py`, `backend/api/uploads.py`):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/sessions` | Create a session and start its runner. |
| `GET` | `/api/sessions/{id}` | Session metadata. |
| `GET` | `/api/sessions/{id}/state` | Editable fields + cover-letter versions. |
| `PATCH` | `/api/sessions/{id}/state` | Patch editable fields (only while paused). |
| `POST` | `/api/sessions/{id}/select-version` | Pick the best cover-letter version. |
| `GET` | `/api/sessions/{id}/traces` | All LLM traces with computed USD cost. |
| `GET` | `/api/sessions/{id}/traces/{card_id}` | One trace in full. |
| `GET` | `/api/profiles` | Reusable applicant profiles. |
| `GET` / `PUT` | `/api/settings` | Default + per-task LLM and model pricing. |
| `GET` | `/api/graph/mermaid` | Static graph topology as Mermaid. |
| `POST` | `/api/uploads/cv` | Upload a PDF CV. |
| `WS` | `/ws/{session_id}` | Bidirectional event stream (see below). |

**WebSocket protocol:**

- **Server → client**: `chat.message`, `action.*`, `llm.*`, `interrupt.request`, `state.update`, `export.ready`, `session.complete`.
- **Client → server**: `{"type": "user.input", "value": <any>}` to resume the graph at the current interrupt.

## Supported LLM providers

- **Anthropic** (Claude — default; `claude-sonnet-4-5` out of the box)
- **OpenAI** (GPT models)
- **Ollama** (local models, via `OLLAMA_BASE_URL`)
- **Generic HTTP** endpoints

## Differences from `app/`

| | `app/` (legacy) | `assistant/` (this) |
| --- | --- | --- |
| UX | Multi-screen wizard (Start → Review → Editor → Questions → Summary) | Single conversation |
| Backend orchestration | Sequential FastAPI route handlers, in-memory `SessionState` | LangGraph StateGraph + per-session runner with interrupts |
| Persistence | In-memory + on-disk conversations | SQLite (sessions, profiles, traces) + LangGraph checkpoints |
| Observability | App-level logging | OTel + OpenInference + per-session event bus → live UI cards |
| Frontend | React + CSS | Next.js 14 App Router + Tailwind |

## License

MIT
