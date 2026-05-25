# Personal Career Assistant

An agentic, conversational helper for the hard parts of switching jobs. Four specialised assistants share one profile, one chat UI, and one observability pipeline:

1. **Cover Letter** — ingest your CV, scrape and analyse a job posting, build a positioning strategy, draft and iteratively refine a tailored cover letter with a hiring-manager feedback loop, and answer common application questions.
2. **Interview Prep** — given a job description plus whatever the company has shared about the upcoming interview, produce a briefing document (likely questions, stories to rehearse, risks to pre-empt, questions to ask).
3. **Career Advisor** — an open-ended conversation about your experience to clarify strengths and weaknesses, with an on-demand SWOT summary.
4. **Interview Evaluator** — upload an audio recording of a real interview; local speech-to-text produces a transcript and an LLM generates a structured performance report (overall score, strengths, weaknesses, per-question analysis, communication critique).

Each assistant is a separate **LangGraph** StateGraph, selected from the landing page. They share the CV/profile prelude and the export step, but otherwise run independently. Built on LangGraph with a human-in-the-loop interrupt model, multi-provider LLM support, OpenTelemetry-based tracing, and a Next.js + Tailwind chat UI.

This is a sibling of the legacy `app/` project. Where `app/` is a multi-screen wizard fixed to cover-letter generation, this assistant is a single conversation per session and can take several shapes depending on which assistant you pick.

## Features

- **Four specialised assistants**, selected on the landing page: Cover Letter, Interview Prep, Career Advisor, Interview Evaluator. Each is its own LangGraph, sharing the CV-intake prelude and the export step.
- **Conversational, single-thread UX**: One chat replaces the wizard. The graph pauses at human-in-the-loop interrupts and resumes when you reply.
- **Shared candidate profile**: CVs are parsed once and saved to the `profiles` table; every subsequent session (any assistant) can load a saved profile and skip the upload.
- **CV intake and profile extraction**: Upload a PDF; the agent parses it and produces a structured candidate profile reused throughout the session.
- **Job ingestion** (cover letter + interview prep): Paste a URL (scraped via `requests` + BeautifulSoup) or raw text. An LLM extraction step fills `job_title`, `company_name`, `job_description`, `company_description`, and `location`.
- **Direct vs. recruiter flows** (cover letter): The agent classifies the posting as a company ad (`direct`) or agency posting (`recruiter`) and routes through `alignment_strategy` or `infer_role` + `position_candidate` accordingly.
- **Company research**: Optional Tavily web search enriches the company description.
- **Cover-letter loop with HM feedback**: Generates a draft, runs a `simulate_hiring_manager` critique pass, and iterates up to `max_hm_iterations` (default 3) or until `quality_threshold` is met. All versions are kept (`cover_letter_versions`) and you can pick the winner.
- **Q&A module** (cover letter): Predefined questions (motivation, salary, experience) plus custom questions, each answered with the same context the cover letter saw.
- **Interview briefing**: Single-pass, Markdown output covering the interview snapshot, your positioning angle, likely questions with answer directions, stories to rehearse, questions to ask the interviewer, and risks to reduce. Uses any "interview context" the candidate pastes (round, interviewer info, HR notes).
- **Career advisor chat**: Multi-turn conversation grounded in the candidate's profile. Type `/swot` at any point to generate a strengths / weaknesses / opportunities / threats synthesis from the transcript.
- **Interview evaluator**: Upload audio (m4a / mp3 / wav / webm / ogg / flac / mp4) from a real interview; faster-whisper transcribes it locally on CPU or GPU; an LLM produces a structured performance report (overall score, decision, per-question breakdown, communication critique, strengths/weaknesses, improvement points) with an iterative review loop. Report respects the session language; transcript stays in the spoken language.
- **Voice input for prompts**: Conversational prompts (mock-interview answers, Q&A, review revisions, etc.) accept dictation through a microphone button next to the textarea. The clip records in-browser (60s cap), is transcribed by the same local Whisper pipeline using the session language as a hint, and the text is inserted into the textarea for review before sending. Audio is ephemeral — never persisted server-side.
- **Multi-format export**: PDF (WeasyPrint), Markdown, JSON, and Google Sheets append. The Markdown export automatically includes whichever artifacts were produced in the session (cover letter, Q&A, interview briefing, SWOT, interview evaluation).
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

Open `http://localhost:3000`, pick one of the four assistants (Cover Letter, Interview Prep, Career Advisor, Interview Evaluator), and start chatting. The backend runs on `http://127.0.0.1:8001` and the WebSocket stream is exposed at `ws://127.0.0.1:8001/ws/{session_id}`.

## Setup

### Prerequisites

- Python 3.12+
- `uv` — install from https://github.com/astral-sh/uv
- Node.js 18+ and npm
- (Optional) `ffmpeg` system binary — required for the Interview Evaluator (`sudo apt install ffmpeg`)
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

### Tavily web search (optional)

Tavily provides the live web-search results used by two nodes:

- **`research_company`** — when the extracted company description is thin (< ~200 chars), it queries Tavily for company background and asks an LLM to synthesise a 3–5 paragraph profile. Wired into the cover-letter and interview-prep graphs.
- **`qa_answer`** — salary questions trigger a Tavily query for market benchmarks before the LLM drafts the answer.

Setup:

1. Sign up at [tavily.com](https://tavily.com) and grab an API key (free tier is plenty for development).
2. Add it to `.env`:
   ```bash
   TAVILY_API_KEY=tvly-...
   ```
3. Restart the backend.

If the key is missing, both nodes degrade gracefully — the assistant just skips the web search and works with whatever context it already has. No code changes needed either way.

### Phoenix tracing (optional)

[Arize Phoenix](https://github.com/Arize-ai/phoenix) is a local LLM-observability UI that ingests OpenTelemetry spans. With Phoenix running, every `call_llm` in the backend shows up as a trace with full prompt, response, tokens, latency, and session tag — useful when debugging prompts or comparing models across tasks.

**You don't need Phoenix to see LLM activity** — the assistant's own right-hand pane (`LLMCardPane`) already shows every call per session via the in-process event bus. Phoenix is only worth installing if you want cross-session analysis, historical comparison, or OTel-native exploration.

**Recommended: run Phoenix in Docker.** The Python packages on PyPI currently have version mismatches between `arize-phoenix` and `arize-phoenix-evals` that break `phoenix serve` even in an isolated `uvx` environment. Docker avoids the entire problem — the image bundles a known-good combination.

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

Restart the backend (`init_otel()` reads the env var at startup), trigger one LLM call from the UI, and open `http://localhost:6006`. Spans are grouped by `session:{id}` — OpenInference's LangChain instrumentation attaches that tag automatically via `backend/llm/service.py`.

Useful Docker commands:

```bash
docker logs -f phoenix          # watch startup
docker stop phoenix             # pause (data persists in the phoenix-data volume)
docker start phoenix            # resume
docker rm -f phoenix            # remove container (volume survives)
docker volume rm phoenix-data   # wipe all traces
```

If the env var is unset, tracing still runs in-process and feeds the UI cards — nothing is exported off-process and Phoenix is not required for normal operation.

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
│   ├── agent/              # LangGraph StateGraphs (one per assistant)
│   │   ├── graph.py            # cover-letter graph wiring
│   │   ├── graph_interview.py  # interview prep graph wiring
│   │   ├── graph_advisor.py    # career advisor graph wiring
│   │   ├── graph_evaluator.py  # interview evaluator graph wiring
│   │   ├── state.py            # ApplicationState (pydantic) — shared across all graphs
│   │   ├── runner.py           # per-session runner; picks the graph by assistant_type
│   │   ├── interrupts.py       # human-in-loop interrupt helpers
│   │   ├── checkpoint.py       # SQLite checkpointer factory
│   │   └── nodes/              # one file per node (greeting, cv_intake, interview_briefing, advisor_chat, evaluator, …)
│   ├── api/
│   │   ├── routes.py       # REST: sessions, state, traces, settings, mermaid
│   │   ├── uploads.py      # CV PDF upload, interview audio upload, voice-prompt transcription
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
│   │   ├── transcribe.py   # faster-whisper speech-to-text (interview audio + voice prompts)
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

### State graphs

Each assistant is its own LangGraph, selected by the `assistant_type` stored on the session row. `backend/agent/runner.py` looks up the builder in `GRAPH_BUILDERS` and compiles the right graph for each session. All four share `ApplicationState` (see `backend/agent/state.py`) — unused fields simply stay empty for a given flow.

**Cover Letter** (`backend/agent/graph.py`) — linear pipeline with a Q&A loop and an export branch:

```
START → greeting → cv_intake → collect_job → extract_info → fill_missing_info
      → confirm_info → research_company → classify_flow → strategy
      → cl_loop → cl_review → qa_menu ⇄ qa_answer → export → (qa_menu | END)
```

- **`cl_loop`** runs `cover_letter_generation` and `simulate_hiring_manager` up to `max_hm_iterations` (default 3) or until `hm_score >= quality_threshold` (default 8.5). Each iteration produces a `CoverLetterVersion` (`version_id`, `text`, `iteration`, `hm_score`, `hm_feedback`).
- **`cl_review`** lets you pick the best version (`POST /api/sessions/{id}/select-version`) before moving on.
- **`qa_menu` / `qa_answer`** form a loop so you can ask multiple predefined or custom questions before exporting.
- **`export_node`** appends to Google Sheets and writes PDF / md / JSON to `DEFAULT_EXPORT_FOLDER`.

**Interview Prep** (`backend/agent/graph_interview.py`) — reuses the cover-letter prelude, then a single-pass briefing:

```
START → greeting → cv_intake → collect_job → extract_info → fill_missing_info
      → confirm_info → research_company → interview_context → interview_briefing
      → export → END
```

- **`interview_context`** asks the candidate for anything HR sent about the upcoming interview (round, interviewer, format, focus areas). Optional — reply `none` to skip.
- **`interview_briefing`** is one LLM call (task `interview_briefing`) that produces a Markdown document with interview snapshot, positioning angle, likely questions with answer directions, STAR stories to prepare, questions to ask, risks to reduce, and a pre-interview checklist.

**Career Advisor** (`backend/agent/graph_advisor.py`) — open chat loop over the candidate's profile:

```
START → greeting → cv_intake → advisor_chat ⇄ advisor_swot → export → END
```

- **`advisor_chat`** runs one conversational turn per invocation and re-enters via a conditional edge. The transcript accumulates in `advisor_transcript: list[ChatTurn]`. Typing `/swot` routes to `advisor_swot`; typing `done` routes to `export`.
- **`advisor_swot`** synthesises a strengths / weaknesses / opportunities / threats document from the profile + transcript and returns control to `advisor_chat`.
- No job intake — this assistant is about the candidate's career, not a specific role.

**Interview Evaluator** (`backend/agent/graph_evaluator.py`) — audio in, structured report out:

```
START → greeting → cv_intake → evaluator_context → evaluator_upload
      → evaluator_transcribe → evaluator_analyze ⇄ evaluator_review
      → export → END
```

- **`evaluator_context`** asks the candidate for any background about the interview round (format, interviewers, focus areas). Optional — reply `none` to skip.
- **`evaluator_upload`** prompts for an audio recording; the file is uploaded via `POST /api/uploads/interview-audio` and stored under `backend/data/audio/{session_id}_{uuid}.{ext}`. Max size is configurable (`transcription.max_file_mb`, default 200 MB).
- **`evaluator_transcribe`** runs faster-whisper locally and streams progress to the chat. On first run, the configured model (default `turbo`, ~800 MB) is downloaded from HuggingFace and cached.
- **`evaluator_analyze`** calls the `analyze_interview_performance` task and validates the response against the `InterviewEvaluation` schema (overall score, decision, per-question breakdown, communication metrics, strengths/weaknesses/improvements).
- **`evaluator_review`** lets the candidate accept the report, retry verbatim, or describe specific revisions. All versions accumulate in `interview_evaluation_versions`.

The full state lives in `backend/agent/state.py` (`ApplicationState`): `assistant_type`, applicant fields, job/company fields, strategy text, `cover_letter_versions`, `qa_items`, `interview_context`, `interview_briefing`, `advisor_transcript`, `advisor_swot`, `interview_recording_path`, `interview_transcript`, `interview_evaluation`, `interview_evaluation_versions`, and `export_results`. Any non-`None` field on a node return is merged into the checkpointed state by LangGraph.

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

- **sessions** — id, phase, `assistant_type` (`cover_letter` | `interview_prep` | `career_advisor` | `interview_evaluator`), `language`, timestamps.
- **profiles** — reusable applicant profiles (CV text + extracted profile), shared across all assistants.
- **traces** — every LLM call ever made in the session (input/output, tokens, model, timing).

LangGraph checkpoints live in their own SQLite file (`backend/agent/checkpoint.py`) so a graph can be resumed across process restarts.

### Frontend

Next.js 14 App Router with Tailwind. Layout is **2/3 chat + 1/3 LLM cards**:

- `app/page.tsx` — landing page with four assistant cards (Cover Letter, Interview Prep, Career Advisor, Interview Evaluator). Each POSTs to `/api/sessions` with the matching `assistant_type` and a chosen `language`.
- `app/session/page.tsx` — main chat. Subscribes to `/ws/{session_id}`, renders `chat.message` events in `ChatPane`, and posts `user.input` messages from `InputBar`. A small badge in the header shows which assistant is active.
- `app/session/details/page.tsx` — inspect / edit the session state (only while the runner is paused at an interrupt).
- `app/session/graph/page.tsx` — renders the live Mermaid topology for the session's assistant, fetched from `GET /api/graph/mermaid?assistant_type=…`.
- `app/session/usage/page.tsx` — per-call tokens + USD cost.
- `app/settings/page.tsx` — default LLM, per-task overrides, model pricing.

## REST + WebSocket API

Main routes (see `backend/api/routes.py`, `backend/api/ws.py`, `backend/api/uploads.py`):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/sessions` | Create a session and start its runner. Body: `{"assistant_type": "cover_letter" \| "interview_prep" \| "career_advisor" \| "interview_evaluator", "language": "English"}` (defaults to `cover_letter` / `English`). |
| `GET` | `/api/sessions/{id}` | Session metadata. |
| `GET` | `/api/sessions/{id}/state` | Editable fields + cover-letter versions. |
| `PATCH` | `/api/sessions/{id}/state` | Patch editable fields (only while paused). |
| `POST` | `/api/sessions/{id}/select-version` | Pick the best cover-letter version. |
| `GET` | `/api/sessions/{id}/traces` | All LLM traces with computed USD cost. |
| `GET` | `/api/sessions/{id}/traces/{card_id}` | One trace in full. |
| `GET` | `/api/profiles` | Reusable applicant profiles. |
| `GET` / `PUT` | `/api/settings` | Default + per-task LLM and model pricing. |
| `GET` | `/api/graph/mermaid` | Static graph topology as Mermaid. Accepts `?assistant_type=…` to pick which graph to render. |
| `POST` | `/api/uploads/cv` | Upload a PDF CV. |
| `POST` | `/api/uploads/interview-audio` | Upload an interview recording for the evaluator. Multipart: `session_id`, `file`. |
| `POST` | `/api/transcribe/voice-prompt` | Transcribe a short voice clip into text for prompt entry. Audio is deleted after transcription. Multipart: `session_id`, `file`. |
| `WS` | `/ws/{session_id}` | Bidirectional event stream (see below). |

**WebSocket protocol:**

- **Server → client**: `chat.message`, `action.*`, `llm.*`, `interrupt.request`, `state.update`, `export.ready`, `session.complete`.
- **Client → server**: `{"type": "user.input", "value": <any>}` to resume the graph at the current interrupt.

## Supported LLM providers

- **Anthropic** (Claude — default; `claude-sonnet-4-5` out of the box)
- **OpenAI** (GPT models)
- **Ollama** (local models, via `OLLAMA_BASE_URL`)
- **Generic HTTP** endpoints

## License

MIT
