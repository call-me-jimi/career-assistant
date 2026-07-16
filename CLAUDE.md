# CLAUDE.md

Project-specific conventions. General coding guidelines live in `~/.claude/CLAUDE.md`.

## Project overview

A personal career assistant with four specialised agents (Cover Letter, Interview Prep, Interview Evaluator, Career Advisor). Python backend: FastAPI + LangGraph with human-in-the-loop interrupts, multi-provider LLM dispatch, SQLite persistence, and OpenTelemetry tracing. Frontend: Next.js 14 App Router + Tailwind.

## Folder map

```
backend/
  agent/
    graph.py / graph_interview.py / graph_advisor.py / graph_evaluator.py  # one LangGraph per assistant
    state.py          # ApplicationState (Pydantic) — shared across all four graphs
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
  storage/            # aiosqlite: sessions, profiles, traces, job journeys, playbook, coaching
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

- [LLM models](docs/llm-models.md) — which files to touch, temperature guards, and a cached pricing table. **When asked for current model prices, fetch live data from the official sources listed in that doc** (Anthropic and OpenAI pricing pages) rather than relying on the cached table.

## Project conventions

- **Package manager: `uv`.** Use `uv run <cmd>` for anything Python (`uv run pytest`, `uv run uvicorn …`), `uv add <pkg>` to add dependencies, `uv sync` to install. Do not call `pip`, `python -m venv`, or a bare `python` — they bypass the locked environment.

- **Prompts are versioned; never edit in place.** Templates under `backend/templates/prompts/` and `backend/templates/system/` follow `{stem}.vN.txt`. `backend/llm/prompts.py` resolves the highest `vN` on disk. To change a prompt, add a new file (`generate_cover_letter.v4.txt` alongside `.v3.txt`), do not mutate the existing one. This preserves history and lets you A/B compare.

- **LangGraph nodes return partial state dicts, not `ApplicationState` instances.** A node is an `async def foo(state: ApplicationState) -> dict` that returns `{"field_a": ..., "phase": "..."}`. LangGraph merges that dict into the checkpointed state. Returning a full `ApplicationState` or omitting the return are both silent bugs.

- **`emit_message` needs a `key=` when it precedes an `interrupt()`.** On resume, LangGraph re-runs the entire node body from the top, so any `emit_message` before the interrupt point will fire again. Pass a stable `key="unique:slug"` so the per-session event bus deduplicates. Messages emitted *after* the interrupt (once, on the post-resume pass) don't need a key.

- **Frontend uses `npm`, not `uv`.** Run `npm run dev`, `npm install`, etc. from `frontend/`. Never use `uv` there.

- **Secrets go in `.env`, never in `settings.json`.** `backend/config/settings.json` is tracked by git and holds only runtime config (models, pricing, locale). API keys must stay in `.env`.

- **`ApplicationState` has fields for all four assistants.** Unused fields stay empty for a given flow — don't remove them or make them conditional. All four graphs share the same state class (`backend/agent/state.py`).

- **`PATCH /api/sessions/{id}/state` requires the runner to be paused at an interrupt.** It returns 409 if the graph is currently running. Only patch state from the details page, not mid-stream.

- **Always flag unmerged worktree changes.** When work is done in a git worktree, end the session with an explicit note if changes haven't been merged to main yet. The dev server runs from the main working copy, so unmerged changes have no effect on the running app.

- **Tag releases with semantic versioning.** Not every commit needs a tag — tag when a meaningful feature or fix is complete and merged to `main`. Use `vMAJOR.MINOR.PATCH`: bump `MINOR` for new features, `PATCH` for bug fixes, `MAJOR` for breaking changes. Current version: `v0.5.1`. After tagging, push with `git push origin <tag>`. At the end of any session that ships a feature or fix, remind the user to tag if appropriate.

- **When bumping the version, change it everywhere.** The version lives in three places that must stay in sync: `pyproject.toml` (`version = "X.Y.Z"`, then run `uv lock`), `frontend/package.json` (`"version"`, then run `npm install --package-lock-only` in `frontend/`), and the "Current version" note in this file. Commit all of them together as the bump commit before tagging.
