# Architecture

How the assistant is put together, for contributors and the curious. For installation see
[SETUP.md](SETUP.md); for model/pricing configuration see [llm-models.md](llm-models.md).

Each of the four assistants is its own **LangGraph** `StateGraph`, selected from the landing page.
They share the CV/profile prelude and the export step; the three job-centric assistants (all but
Career Advisor) also share the job-intake prelude and **job journeys** (per-job persistence across
sessions — see below). The stack is LangGraph with a human-in-the-loop interrupt model, a
multi-provider LLM service, OpenTelemetry tracing, SQLite persistence, and a Next.js + Tailwind
chat UI.

## Repository layout

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
│   │   ├── routes.py       # REST: sessions, state, traces, journeys, profiles, playbook, stats, settings, mermaid
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
│   │   ├── db.py           # aiosqlite init + idempotent migrations
│   │   ├── sessions.py     # session lifecycle
│   │   ├── profiles.py     # reusable applicant profiles
│   │   ├── journeys.py     # job journeys: per-job artifacts shared across sessions
│   │   ├── applications.py # completed cover-letter applications + HM iterations
│   │   ├── playbook.py     # per-profile learned playbook
│   │   ├── suggestions.py  # LLM-proposed candidate-profile edits awaiting review
│   │   ├── coaching_insights.py  # evaluator findings fed into interview prep
│   │   ├── stats.py        # global usage aggregates for the dashboard
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
│   │   ├── dashboard/      # global usage + cost stats across all sessions
│   │   ├── jobs/           # job-journey list + [id] detail
│   │   ├── profiles/       # applicant-profile list + [id] detail (playbook, suggestions)
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

## State graphs

Each assistant is its own LangGraph, selected by the `assistant_type` stored on the session row.
`backend/agent/runner.py` looks up the builder in `GRAPH_BUILDERS` and compiles the right graph for
each session. All four share `ApplicationState` (see `backend/agent/state.py`) — unused fields
simply stay empty for a given flow.

**Cover Letter** (`backend/agent/graph.py`) — linear pipeline with a Q&A loop, an export branch,
and an end-of-session learning tail:

```
START → greeting → cv_intake → select_journey → collect_job → extract_info
      → language_switch → fill_missing_info → confirm_info → research_company
      → classify_flow → strategy → cl_loop → cl_review → qa_menu ⇄ qa_answer
      → export → post_export → (qa_menu | synthesize_learning
      → review_learned_suggestion → END)
```

- **`select_journey`** offers to continue a previously started job — see
  [Job journeys](#job-journeys). Continuing skips ahead past every step whose data already exists.
- **`language_switch`** offers to switch the session output language when the job ad is written in
  a different language than the conversation.
- **`cl_loop`** runs `cover_letter_generation` and `simulate_hiring_manager` up to
  `max_hm_iterations` (default 3) or until `hm_score >= quality_threshold` (default 8.5). Each
  iteration produces a `CoverLetterVersion` (`version_id`, `text`, `iteration`, `hm_score`,
  `hm_feedback`).
- **`cl_review`** lets you pick the best version (`POST /api/sessions/{id}/select-version`) before
  moving on.
- **`qa_menu` / `qa_answer`** form a loop so you can ask multiple predefined or custom questions
  before exporting.
- **`export_node`** appends to Google Sheets and writes PDF / md / JSON to `DEFAULT_EXPORT_FOLDER`.
- **`post_export`** asks whether to return to the Q&A menu or wrap up; on wrap-up
  **`synthesize_learning`** and **`review_learned_suggestion`** run the learning tail — see
  [Per-profile learning](#per-profile-learning).

**Interview Prep** (`backend/agent/graph_interview.py`) — reuses the cover-letter prelude, then a
briefing with a revision loop and a practice menu:

```
START → greeting → load_coaching_history → cv_intake → select_journey → collect_job
      → extract_info → language_switch → fill_missing_info → confirm_info
      → research_company → interview_context → interview_briefing → interview_review
      → interview_menu ⇄ (interview_mock ⇄ interview_mock_answer | interview_practice
      | interview_tech | interview_questions) → export → post_export
      → (interview_menu | END)
```

- **`load_coaching_history`** silently loads the profile's coaching insights (from past interview
  evaluations) so the briefing accounts for previous performance.
- **`interview_context`** asks the candidate for anything HR sent about the upcoming interview
  (round, interviewer, format, focus areas). Optional — reply `none` to skip.
- **`interview_briefing`** is one LLM call (task `interview_briefing`) that produces a Markdown
  document with interview snapshot, positioning angle, likely questions with answer directions, STAR
  stories to prepare, questions to ask, risks to reduce, and a pre-interview checklist.
- **`interview_review`** loops revisions until the briefing is accepted; the accepted version is
  saved to the job journey.
- **`interview_menu`** offers four practice sub-flows and loops back until `done`: `mock`
  (open-ended mock interview — the LLM asks, you answer, it gives feedback), `practice` (sample
  answers to classic questions), `tech` (focused technical/domain refresher), and `questions`
  (questions to ask the interviewer).

**Career Advisor** (`backend/agent/graph_advisor.py`) — open chat loop over the candidate's profile:

```
START → greeting → cv_intake → advisor_chat ⇄ advisor_swot → export → END
```

- **`advisor_chat`** runs one conversational turn per invocation and re-enters via a conditional
  edge. The transcript accumulates in `advisor_transcript: list[ChatTurn]`. Typing `/swot` routes to
  `advisor_swot`; typing `done` routes to `export`.
- **`advisor_swot`** synthesises a strengths / weaknesses / opportunities / threats document from
  the profile + transcript and returns control to `advisor_chat`.
- No job intake — this assistant is about the candidate's career, not a specific role.

**Interview Evaluator** (`backend/agent/graph_evaluator.py`) — audio in, structured report out.
Shares the job-intake prelude so the evaluation is grounded in the actual job:

```
START → greeting → cv_intake → select_journey → collect_job → extract_info
      → language_switch → fill_missing_info → confirm_info → evaluator_context
      → evaluator_upload ⇄ evaluator_transcribe → evaluator_analyze ⇄ evaluator_review
      → export → post_export → END
```

- **`evaluator_context`** asks the candidate for any background about the interview round (format,
  interviewers, focus areas). Optional — reply `none` to skip.
- **`evaluator_upload`** prompts for an audio recording; the file is uploaded via
  `POST /api/uploads/interview-audio` and stored under
  `backend/data/audio/{session_id}_{uuid}.{ext}`. Max size is configurable
  (`transcription.max_file_mb`, default 200 MB).
- **`evaluator_transcribe`** runs faster-whisper locally and streams progress to the chat. On first
  run, the configured model (default `turbo`, ~800 MB) is downloaded from HuggingFace and cached.
- **`evaluator_analyze`** calls the `analyze_interview_performance` task and validates the response
  against the `InterviewEvaluation` schema (overall score, decision, per-question breakdown,
  communication metrics, strengths/weaknesses/improvements).
- **`evaluator_review`** lets the candidate accept the report, retry verbatim, or describe specific
  revisions. All versions accumulate in `interview_evaluation_versions`. Accepting stores an
  evaluation summary on the job journey and a coaching insight for future Interview Prep sessions.

The full state lives in `backend/agent/state.py` (`ApplicationState`): `assistant_type`, applicant
fields, job/company fields, `journey_id` / `journey_query`, strategy text,
`cover_letter_versions`, `pending_suggestion`, `qa_items`, `interview_context`,
`interview_briefing` (+ versions and revision feedback), `mock_interview_transcript`,
`interview_extras`, `coaching_history`, the `interview_recording_*` / `interview_transcript` /
`interview_evaluation*` fields, `advisor_transcript`, `advisor_swot`, and `export_selection` /
`export_results` / `export_delivery`. Any non-`None` field on a node return is merged into the
checkpointed state by LangGraph.

## Job journeys

A **job journey** is the per-job record that lets the Cover Letter, Interview Prep, and Interview
Evaluator assistants (not Career Advisor) continue the same job across sessions instead of starting
over.

- **`select_journey`** (`backend/agent/nodes/select_journey.py`) runs right after `cv_intake` in
  all three graphs. It lists recent journeys as a numbered pick list with artifact badges
  (cover letter ✓ / briefing ✓ / evaluated ✓); the user can continue one, filter the list by
  typing a company name, or start fresh with a URL / pasted text. Continuing seeds the stored
  job, company, strategy, and artifact fields into state and routes to the earliest step whose
  data is still missing — completed steps are skipped, not re-run.
- **Persistence points**: `confirm_info` creates the journey (or updates a matching one);
  `research_company`, `strategy`, `synthesize_learning` (final cover letter), `interview_review`
  (accepted briefing), and the evaluator's accept step each write their artifact back. The storage
  layer (`backend/storage/journeys.py`) automatically stamps `cover_letter_at` /
  `interview_briefing_at` / `evaluation_summary_at` when the matching artifact is written.
- **UI**: `app/jobs/page.tsx` lists journeys with search, four-way sort, paging, and delete;
  `app/jobs/[id]/page.tsx` shows the job ad, research, strategies, and each artifact with its
  generation date.
- **API**: `GET /api/journeys`, `GET /api/journeys/{id}`, `DELETE /api/journeys/{id}`.

## Per-profile learning

Two feedback loops persist knowledge per applicant profile:

- **Cover-letter playbook.** When a cover-letter session wraps up, `synthesize_learning` persists
  the completed application (`application_records` + `application_hm_iterations`) and runs one LLM
  reflection over this session plus recent history. The result updates the profile's **playbook**
  (structured guidance injected into future cover-letter generation) and may propose an edit to
  the candidate profile. High-confidence proposals are offered in-chat by
  `review_learned_suggestion`; pending ones can also be approved or rejected from the profile
  detail page.
- **Interview coaching.** Accepted interview evaluations store a **coaching insight**;
  `load_coaching_history` loads the profile's insights at the start of each Interview Prep session
  so briefings account for past performance.

## Session runner and human-in-the-loop

`backend/agent/runner.py` (`SessionRunner`) drives one compiled graph per session as a background
asyncio task. It:

1. Streams the graph forward until it hits an interrupt (or finishes).
2. Publishes an `interrupt.request` event on the per-session event bus.
3. Awaits the next message from its input queue (fed by the WebSocket).
4. Resumes the graph with `Command(resume=…)`.

While paused, REST clients may patch editable state fields via `PATCH /api/sessions/{id}/state`
(whitelist in `routes.py:EDITABLE_FIELDS`). Updates while the runner is *not* paused return 409.

## LLM service and prompt versioning

`backend/llm/service.py` dispatches to Anthropic, OpenAI, Ollama, or a generic HTTP endpoint based
on the resolved `LLMConfig`. Each task in `KNOWN_TASKS` (see `backend/config.py`) may override the
default model/provider via `task_llm_configs` in `settings.json`, edited from the **Settings** page.

Prompts are versioned files under `backend/templates/prompts/{stem}.vN.txt` and
`backend/templates/system/{stem}.system.vN.txt`. Resolution always picks the **highest `vN`** on
disk — add a new version by creating a new file, never by editing an existing one.

## Observability

`init_otel()` (called in the FastAPI lifespan) configures an OpenTelemetry tracer and installs
**OpenInference** LangChain instrumentation. Each LLM call:

1. Emits OTel spans (optionally exported to `PHOENIX_COLLECTOR_ENDPOINT`).
2. Goes through a LangChain callback that persists a trace row (`backend/storage/traces.py`) with
   prompt, response, model, input/output tokens, and timing.
3. Publishes an `llm.*` event on the per-session event bus, which the WebSocket forwards to the UI.

The UI's right-hand pane lists every call as a card; clicking one opens the full prompt/response
view. USD cost is computed on the fly from `model_pricing` in settings, so adding a new model only
requires a pricing entry.

## Storage

SQLite via `aiosqlite` (`backend/storage/db.py`, with idempotent column migrations at startup).
Tables:

- **sessions** — id, phase, `assistant_type` (`cover_letter` | `interview_prep` | `career_advisor`
  | `interview_evaluator`), `language`, timestamps.
- **profiles** — reusable applicant profiles (CV text + extracted profile), shared across all
  assistants.
- **traces** — every LLM call ever made in the session (input/output, tokens, model, timing).
- **job_journeys** — one row per job: URL / title / company / description, research, strategies,
  cover letter, interview briefing, evaluation summary, plus per-artifact `*_at` timestamps.
  Indexed per profile.
- **application_records** / **application_hm_iterations** — completed cover-letter applications and
  their hiring-manager iterations; the history `synthesize_learning` reflects over.
- **profile_playbook** — per-profile learned guidance injected into cover-letter generation.
- **profile_suggestions** — LLM-proposed candidate-profile edits awaiting approve / reject.
- **coaching_insights** — evaluator findings surfaced to later interview-prep sessions.

LangGraph checkpoints live in their own SQLite file (`backend/agent/checkpoint.py`) so a graph can
be resumed across process restarts.

## Frontend

Next.js 14 App Router with Tailwind. Layout is **2/3 chat + 1/3 LLM cards**:

- `app/page.tsx` — landing page with four assistant cards. Each POSTs to `/api/sessions` with the
  matching `assistant_type` and a chosen `language`.
- `app/session/page.tsx` — main chat. Subscribes to `/ws/{session_id}`, renders `chat.message`
  events in `ChatPane`, and posts `user.input` messages from `InputBar`. A header badge shows the
  active assistant.
- `app/session/details/page.tsx` — inspect / edit the session state (only while the runner is
  paused at an interrupt).
- `app/session/graph/page.tsx` — renders the live Mermaid topology for the session's assistant,
  fetched from `GET /api/graph/mermaid?assistant_type=…`.
- `app/session/usage/page.tsx` — per-call tokens + USD cost.
- `app/jobs/page.tsx` / `app/jobs/[id]/page.tsx` — job-journey list (search, sort, paging, delete)
  and detail (job ad, research, strategies, artifacts with generation dates).
- `app/profiles/page.tsx` / `app/profiles/[id]/page.tsx` — applicant profiles; the detail page
  shows CV text, candidate profile, tone notes, the learned playbook, and pending profile
  suggestions to approve or reject.
- `app/dashboard/page.tsx` — global usage: sessions, LLM calls, tokens, and USD cost per assistant
  (backed by `GET /api/stats`).
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
| `GET` | `/api/sessions/{id}/exports/{kind}` | Stream a previously generated export file for download. |
| `GET` | `/api/profiles` | Reusable applicant profiles. |
| `GET` / `DELETE` | `/api/profiles/{id}` | One profile in full / delete it. |
| `GET` / `PATCH` | `/api/profiles/{id}/playbook` | Read / edit the profile's learned playbook (`DELETE …/playbook/{category}/{index}` removes one entry). |
| `GET` | `/api/profiles/{id}/suggestions` | Pending profile suggestions (`POST …/suggestions/{sid}/approve` or `…/reject` resolves one). |
| `GET` | `/api/journeys` | All job journeys (artifacts + timestamps). |
| `GET` / `DELETE` | `/api/journeys/{id}` | One journey in full / delete it. |
| `GET` | `/api/stats` | Global usage aggregates (sessions, calls, tokens, cost per assistant) for the dashboard. |
| `GET` / `PUT` | `/api/settings` | Default + per-task LLM and model pricing. |
| `GET` | `/api/graph/mermaid` | Static graph topology as Mermaid. Accepts `?assistant_type=…` to pick which graph to render. |
| `POST` | `/api/uploads/cv` | Upload a PDF CV. |
| `POST` | `/api/uploads/interview-audio` | Upload an interview recording for the evaluator. Multipart: `session_id`, `file`. |
| `POST` | `/api/transcribe/voice-prompt` | Transcribe a short voice clip into text for prompt entry. Audio is deleted after transcription. Multipart: `session_id`, `file`. |
| `WS` | `/ws/{session_id}` | Bidirectional event stream (see below). |

**WebSocket protocol:**

- **Server → client**: `chat.message`, `action.*`, `llm.*`, `interrupt.request`, `state.update`,
  `export.ready`, `session.complete`, `session.error`.
- **Client → server**: `{"type": "user.input", "value": <any>}` to resume the graph at the current
  interrupt.
