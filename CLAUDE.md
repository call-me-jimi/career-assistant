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
  storage/            # aiosqlite: sessions, profiles, traces, job journeys, events, playbook, coaching
  tools/              # scraper, cv_parser, exporters, web_search
  templates/
    prompts/          # user prompt templates — {stem}.vN.txt
    system/           # system prompt templates — {stem}.system.vN.txt
  config/settings.json  # runtime config (no secrets)
  config.py           # loads .env + settings.json
  main.py             # FastAPI app entry point
frontend/             # Next.js; use npm (not uv) inside this directory
  app/
    page.tsx          # landing — status strip, pick assistant, create session
    session/          # main chat + LLM cards; details, graph, usage subroutes
    jobs/             # labelled "Applications" in the nav — the tracker table;
                      #   [id] = one job's timeline, rounds, feedback, outcome
    learned/          # playbook per CV + "is the evaluator honest?" calibration
    profiles/         # CV profiles; [id] = one profile
    dashboard/        # usage across all sessions: calls, tokens, cost
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

- **An application's status is derived, never stored.** There is no `status` column. `derive_status()` in `backend/storage/journeys.py` reads five dates on `job_journeys` (`applied_at`, `on_hold_at`, `rejected_at`, `dropped_at`, `offer_at`) plus `job_interviews.scheduled_at`, first match wins. The API returns `status` read-only; `PATCH /api/journeys/{id}` accepts dates only. Adding a status column would let it drift from the dates that define it.

- **One rung of that ladder reads the clock.** `silent` means applied, nothing since, and longer ago than `quiet_after_days` (`settings.json`, default 30) — so a row's status changes overnight with nothing written. That is only safe because status is never stored. Two consequences: **every test that asserts a status must pass `now=`**, or it goes stale as its fixtures age; and callers that show a status to the user pass the configured `quiet_after_days` (the API reads it once per request rather than per row). Only the employer resets the clock — `last_contact_at()` counts rounds and feedback, never events, because a follow-up you sent is not a reply.

- **`job_feedback.outcome` is derived too, and never a parameter.** `add_feedback()` snapshots it from `derive_status()` as the row is written — there is no `outcome` argument and `FeedbackPayload` forbids extras, so a client that sends one gets a 422 rather than silently setting nothing. An outcome and its reason are captured together by `POST /api/journeys/{id}/outcome`, which writes the date first so the snapshot can see it. Splitting those two writes is what let the column drift from the dates before v0.13.0; `"ghosted"` survives in `OUTCOMES` only so older rows still load.

- **`applied_at` is the user's answer, not a side effect of exporting.** The `log_application` node asks for tracker notes and whether the application was actually submitted, once per session, before `export_node` writes anything — both answers also fill the spreadsheet row (`Notes`, and `Status`/`Submission`, which say `Draft` and stay blank until the user confirms). `no` leaves the journey a `draft`. The migration that dated pre-tracker journeys from their cover letter is therefore one-shot, guarded by `PRAGMA user_version` in `backend/storage/db.py`; rerunning it — as it did on every startup before v0.15.0 — would promote every deliberate "not sent yet" to `applied`.

- **`PATCH /api/sessions/{id}/state` requires the runner to be paused at an interrupt.** It returns 409 if the graph is currently running. Only patch state from the details page, not mid-stream.

- **Substantially change the landing page, renew its screenshot.** `README.md` opens with `docs/screenshots/landing-page.png`, so a redesign that isn't reshot leaves the project's first impression showing a UI that no longer exists. The shot is generated, not taken: `uv run python docs/screenshots/seed_demo.py`, with the frontend dev server up (the backend is not needed). **Never reshoot against your own database** — this repo is public, and the landing page puts the real state of a real job search on screen. The seeder invents journeys, lets `journeys_summary()` derive the counters from their dates, and asserts the tiles still partition the total before writing the file, so a strip that stops adding up fails the run instead of shipping to the README.

- **Always flag unmerged worktree changes.** When work is done in a git worktree, end the session with an explicit note if changes haven't been merged to main yet. The dev server runs from the main working copy, so unmerged changes have no effect on the running app.

- **Tag releases with semantic versioning.** Not every commit needs a tag — tag when a meaningful feature or fix is complete and merged to `main`. Use `vMAJOR.MINOR.PATCH`: bump `MINOR` for new features, `PATCH` for bug fixes, `MAJOR` for breaking changes. Current version: `v0.14.2`. After tagging, push with `git push origin <tag>`. At the end of any session that ships a feature or fix, remind the user to tag if appropriate.

- **When bumping the version, change it everywhere.** The version lives in three places that must stay in sync: `pyproject.toml` (`version = "X.Y.Z"`, then run `uv lock`), `frontend/package.json` (`"version"`, then run `npm install --package-lock-only` in `frontend/`), and the "Current version" note in this file. Commit all of them together as the bump commit, then **push immediately** — never leave a version bump uncommitted or unpushed. (Tagging is separate and still gated on the user.)
