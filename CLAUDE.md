# CLAUDE.md

Project-specific conventions. General coding guidelines live in `~/.claude/CLAUDE.md`.

## Project overview

A personal career assistant with three specialised agents (Cover Letter, Interview Prep, Career Advisor). Python backend: FastAPI + LangGraph with human-in-the-loop interrupts, multi-provider LLM dispatch, SQLite persistence, and OpenTelemetry tracing. Frontend: Next.js 14 App Router + Tailwind.

## Folder map

```
backend/
  agent/
    graph.py / graph_interview.py / graph_advisor.py  # one LangGraph per assistant
    state.py          # ApplicationState (Pydantic) — shared across all three graphs
    nodes/            # one file per node
    runner.py         # SessionRunner: background asyncio task per session
    interrupts.py     # human-in-the-loop helpers
    checkpoint.py     # SQLite checkpointer factory
  api/
    routes.py         # REST endpoints
    ws.py             # /ws/{session_id} WebSocket stream
    uploads.py        # CV PDF upload
  llm/
    service.py        # multi-provider dispatch (Anthropic, OpenAI, Ollama, generic HTTP)
    prompts.py        # versioned prompt resolution
    schemas.py        # task-specific response schemas
  storage/            # aiosqlite: sessions, profiles, traces
  tools/              # scraper, cv_parser, exporters, web_search
  templates/
    prompts/          # user prompt templates — {stem}.vN.txt
    system/           # system prompt templates — {stem}.system.vN.txt
  config/settings.json  # runtime config (no secrets)
  config.py           # loads .env + settings.json
  main.py             # FastAPI app entry point
frontend/             # Next.js; use npm (not uv) inside this directory
  app/
    page.tsx          # landing — pick assistant, create session
    session/          # main chat + LLM cards
    settings/         # LLM defaults + per-task overrides + model pricing
```

## How-to guides

- [Adding new LLM models](docs/adding-models.md) — which files to touch, temperature guards, pricing

## Project conventions

- **Package manager: `uv`.** Use `uv run <cmd>` for anything Python (`uv run pytest`, `uv run uvicorn …`), `uv add <pkg>` to add dependencies, `uv sync` to install. Do not call `pip`, `python -m venv`, or a bare `python` — they bypass the locked environment.

- **Prompts are versioned; never edit in place.** Templates under `backend/templates/prompts/` and `backend/templates/system/` follow `{stem}.vN.txt`. `backend/llm/prompts.py` resolves the highest `vN` on disk. To change a prompt, add a new file (`generate_cover_letter.v4.txt` alongside `.v3.txt`), do not mutate the existing one. This preserves history and lets you A/B compare.

- **LangGraph nodes return partial state dicts, not `ApplicationState` instances.** A node is an `async def foo(state: ApplicationState) -> dict` that returns `{"field_a": ..., "phase": "..."}`. LangGraph merges that dict into the checkpointed state. Returning a full `ApplicationState` or omitting the return are both silent bugs.

- **`emit_message` needs a `key=` when it precedes an `interrupt()`.** On resume, LangGraph re-runs the entire node body from the top, so any `emit_message` before the interrupt point will fire again. Pass a stable `key="unique:slug"` so the per-session event bus deduplicates. Messages emitted *after* the interrupt (once, on the post-resume pass) don't need a key.

- **Frontend uses `npm`, not `uv`.** Run `npm run dev`, `npm install`, etc. from `frontend/`. Never use `uv` there.

- **Secrets go in `.env`, never in `settings.json`.** `backend/config/settings.json` is tracked by git and holds only runtime config (models, pricing, locale). API keys must stay in `.env`.

- **`ApplicationState` has fields for all three assistants.** Unused fields stay empty for a given flow — don't remove them or make them conditional. All three graphs share the same state class (`backend/agent/state.py`).

- **`PATCH /api/sessions/{id}/state` requires the runner to be paused at an interrupt.** It returns 409 if the graph is currently running. Only patch state from the details page, not mid-stream.
