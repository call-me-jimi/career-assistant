# Plan — Employer feedback on a job

**Goal.** A *job* (one job ad = one `job_journeys` row) becomes the hub that owns every asset
generated for it. The user can inspect those assets, see which interview rounds were already
prepared, and attach the feedback the company gave them. That feedback then informs future
applications — immediately through the strategy and briefing prompts, and over time through the
per-profile playbook.

Status: planned, not implemented. Target release: `v0.11.0`.

---

## 1. What exists today

| Concern | Where | Gap |
| --- | --- | --- |
| Job = job ad + assets | `job_journeys` (`backend/storage/journeys.py`) | No feedback, no outcome |
| Interview rounds | `job_interviews` (`backend/storage/interviews.py`) | `GET /api/journeys/{id}` doesn't return them; job page can't show them |
| Per-profile learning | `profile_playbook` → `render_playbook_for_prompt` → `cl_loop` | Learns only from *simulated* HM feedback, never from real employers |
| Interview coaching | `coaching_insights` → `load_coaching_history` → briefing prompts | Learns only from *self*-evaluations |
| Suggestion inbox | `profile_suggestions` + `synthesize_learning` node | Reusable as-is |

The learning plumbing is already there. This feature adds a **real-world signal** to it.

---

## 2. Data model

New table (goes in `SCHEMA` in `backend/storage/db.py` — `executescript` handles creation, no
migration needed):

```sql
CREATE TABLE IF NOT EXISTS job_feedback (
    feedback_id   TEXT PRIMARY KEY,
    journey_id    TEXT NOT NULL,
    profile_id    TEXT,
    interview_ids TEXT NOT NULL DEFAULT '[]',        -- JSON list; [] = the whole process
    stage         TEXT NOT NULL DEFAULT 'unknown',   -- application|screening|interview|final|offer
    outcome       TEXT NOT NULL DEFAULT 'rejected',  -- rejected|ghosted|withdrawn|offer
    source        TEXT NOT NULL DEFAULT '',          -- recruiter|hiring_manager|ats|other
    feedback_text TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    FOREIGN KEY (journey_id) REFERENCES job_journeys(journey_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_feedback_journey ON job_feedback(journey_id, created_at);
CREATE INDEX IF NOT EXISTS idx_job_feedback_profile ON job_feedback(profile_id, created_at DESC);
```

Design notes:

- **Verbatim, not pre-classified.** `feedback_text` stores the employer's words as pasted. The
  LLM interprets at injection time; no upfront categorisation to get wrong.
- **Multiple rows per job.** Recruiter feedback after the screen and hiring-manager feedback after
  the onsite are separate rows — which is why this is a table, not columns on `job_journeys`.
- **One row can span rounds.** A recruiter usually summarises the whole loop — screening, hiring
  manager, leadership — in a single message, so a scalar `interview_id` would be wrong. `[]` means
  "the whole process", `["a"]` pins it to one round, `["a","b"]` spans two. The empty case is the
  common one and is load-bearing: §4 maps it onto *every* evaluated round of that job.
- **`feedback_text` may be empty.** "Rejected, no reason given" is a valid record for the job
  timeline. Rows with empty text are excluded from every prompt-injection query.
- **`outcome = 'offer'` is allowed.** Positive feedback is the same shape and is the most valuable
  learning signal there is; the prompts frame it as "what worked".
- **`outcome` is for the timeline, never for learning.** It records what happened so the job list
  and dashboard can show it. It is deliberately excluded from the calibration payload (§4): a
  rejection is not evidence that the evaluator scored too high, and the candidate has no way to know
  whether it was. Only the *content* of the feedback ever teaches anything.
- **`profile_id` is derived server-side** from the journey row, never taken from the client.
- **`ON DELETE CASCADE` is declarative only** — resolved in step 1. `PRAGMA foreign_keys` is off
  (SQLite's default) and `connect()` does not set it, so the cascade never fires. Enabling it
  globally would mean reshaping `connect()` into an async context manager that issues the pragma per
  connection, which is well beyond this feature; `delete_journey` deletes `job_feedback` rows
  explicitly instead. The FK stays declared as documentation.

Two guarded `ALTER TABLE`s in `_migrate()`, matching the existing pattern:

```sql
ALTER TABLE profile_playbook  ADD COLUMN employer_feedback_themes TEXT NOT NULL DEFAULT '[]'
ALTER TABLE coaching_insights ADD COLUMN journey_id   TEXT
ALTER TABLE coaching_insights ADD COLUMN interview_id TEXT
```

Playbook theme items are `{"theme": str, "evidence": str}`.

`coaching_insights` currently records only `session_id`, so a stored evaluation cannot be traced
back to the job or the round it belongs to — which blocks §4 entirely. `save_coaching_insight`
(called at `backend/agent/nodes/evaluator.py:240`) gains two arguments; the node already holds
`state.journey_id` and `state.interview_id`. Rows written before this stay `NULL` and are skipped by
the pairing query.

---

## 3. How the feedback reaches future applications

Two channels with different latencies. Deliberately non-overlapping, so no prompt receives the same
signal twice.

| Consumer | Channel | Latency | Prompt change |
| --- | --- | --- | --- |
| `strategy` node — alignment strategy | Raw recent feedback | Next session | `generate_alignment_strategy.v3.txt` |
| `cl_loop` — cover letter generation | Playbook themes via the existing `{{ profile_playbook }}` var | After one synthesis pass | **none** |
| `interview_briefing` node | Raw recent feedback | Next session | `generate_interview_briefing.v5.txt` |
| `evaluator` node — performance analysis | **Calibration pairs** (§4) | Next session | `analyze_interview_performance.v5.txt` + `interview_evaluator.system.v5.txt` |
| `synthesize_learning` node | Raw feedback as synthesis input | — | `synthesize_learning.v2.txt` |

The cover letter is reached **twice, indirectly**: through the alignment strategy it consumes in the
same session (immediate), and through the distilled playbook (durable). It gets no direct raw
injection — that would triple-count the same feedback and crowd the prompt.

### Selection rules for raw injection

- Gate on `settings.learning_enabled and state.profile_id`, mirroring `cl_loop`'s playbook gate.
- Take the `settings.feedback_window_n` (default 5) most recent non-empty entries for the profile.
- **Always** include entries for the same `company_name` even if outside the window — re-applying to
  a company that already told you why they said no is the highest-value case.
- No stage filtering. Application-stage feedback ("your CV never showed team leadership") is just as
  relevant to a briefing as interview-stage feedback; each entry carries its stage and round labels
  so the model can weigh it. The recency window alone caps the volume.

### Guardrail framing — required in every new template

Rejection feedback injected naively produces defensive, apologetic letters ("Although I have
limited Kubernetes experience…"). Each template's feedback block must state:

> These are real messages from employers about past applications. Use them to decide what to
> emphasise and which concerns to pre-empt with concrete evidence. Never mention a past rejection,
> never apologise, never hedge. One piece of feedback is a data point, not a rule — only treat a
> theme as established if it recurs.

### Distillation (channel 2)

Runs inside the existing `synthesize_learning_node` at cover-letter session end, **not** in the POST
handler — no LLM calls from REST, and it reuses the node's playbook upsert and suggestion inbox.

`synthesize_learning.v2.txt` gains an `employer_feedback` input; the system prompt gets a matching
`.system.v2.txt` describing `playbook.employer_feedback_themes` in the response contract. The node
passes recent feedback, the LLM promotes recurring themes, `upsert_playbook` normalises and stores
them, and `render_playbook_for_prompt` renders them under:

> Recurring themes in real employer feedback — address these proactively:

Because the cover-letter templates already interpolate `{{ profile_playbook }}`, themes reach
generation with zero template work.

**Consequence:** feedback added today influences the playbook only after the *next* cover-letter
session ends. That is acceptable because channel 1 already makes it effective in that same session.

---

## 4. Evaluator calibration — the reason this feature is worth building

The Interview Evaluator judges a transcript and produces a score, a decision and a list of
weaknesses. Today nothing ever tells it whether it was **right**. Employer feedback is exactly that
missing label: the evaluator's read of the interview versus how the interviewer actually perceived
the candidate.

### Pairing, at read time

No new table and no extra LLM pass. A storage query joins what already exists:

```
list_evaluator_calibration(profile_id, limit) -> list[pair]
```

For each non-empty `job_feedback` row belonging to the profile, find the evaluations it covers:

- `interview_ids` non-empty → the `coaching_insights` rows for exactly those rounds;
- `interview_ids == []` → **every** round of that journey that has an evaluation. This is the
  recruiter-summary case: one message about the whole loop becomes a calibration pair against the
  screening read, the hiring-manager read and the leadership read separately.

Each pair carries:

```json
{
  "company_name": "...", "job_title": "...", "round": "Hiring manager interview",
  "assistant_said": { "overall_score": 7.2, "decision": "lean_hire",
                      "summary": "...", "weaknesses": [...], "improvements": [...] },
  "employer_said": "...", "stage": "interview", "source": "hiring_manager"
}
```

`outcome` is deliberately absent. `source` is present because who said it is a reliability prior —
a recruiter's form letter and an interviewer's debrief are not equally informative, and the
candidate always knows which one they got.

Computing at read time means no staleness: feedback added after an evaluation, or an evaluation run
after feedback was recorded, both produce the pair on the next query.

### Injection and framing

`analyze_interview_performance.v5.txt` gains a `calibration` block, with a matching
`interview_evaluator.system.v5.txt`. The framing matters as much as the data:

> Below are past interviews where both your own assessment and the employer's message are known.
> Use them to calibrate this assessment: look for dimensions you consistently missed, and for a
> systematic tendency to be harsher or more generous than the employer.
>
> Read them under these constraints:
>
> - The employer's message is evidence about **how the candidate was perceived**, not about
>   objective performance — they saw one conversation, you see the full transcript.
> - Whether the candidate was hired or rejected is **not** shown to you, because it is not evidence
>   about your accuracy. Candidates are turned down for internal hires, frozen budgets and stronger
>   applicants. Only what was said about the candidate counts.
> - Many of these messages name nothing specific about the candidate at all — "a very strong field",
>   "not the right fit at this time". Such a message carries **no** calibration information. Pass
>   over it; do not mine it for an implied criticism.
> - Weight by who spoke. An interviewer's or hiring manager's debrief reflects the room; a
>   recruiter's form letter reflects a template.
> - One pair is never enough to conclude you are miscalibrated. Say so only when the same gap shows
>   up in at least two independent pairs.
>
> Where they repeatedly flagged something you did not raise, that is a blind spot; where they
> praised something you marked as weak, your bar is too high. Do not simply restate their verdict.

Gate on `settings.learning_enabled and state.profile_id`, and render nothing when there are no
pairs — a fresh profile must produce byte-identical prompts to the pre-feature version.

### Showing the delta to the user

Where a round has both an evaluation and covering feedback, the job page renders them side by side —
"the assistant said / they said". This is the single most useful artefact in the feature for a human
reader, and it costs almost nothing once both sections from §5 exist.

---

## 5. Job detail page — the asset hub

`GET /api/journeys/{id}` currently returns the bare journey row. Enrich it:

```json
{ "...journey fields unchanged...",
  "interviews": [...], "feedback": [...], "calibration": [...] }
```

Keeping the existing top-level fields untouched means the current `Journey` type on the frontend
stays valid; the page only adds sections.

New page sections (`frontend/app/jobs/[id]/page.tsx`):

1. **Interview rounds** — one card per `job_interviews` row: type label (`describe_type`), free-text
   label, whether a briefing and an evaluation exist and when, expandable text. Render the existing
   journey-level "Interview briefing" block **only when `interviews` is empty** (the v0.9.0
   migration files legacy briefings as an `'Earlier round'` row, so this is a rare fallback).
2. **Feedback from the company** — entry list (date · stage · outcome · source · covered rounds ·
   verbatim text · delete) plus an add form: stage select, outcome select, source select, textarea,
   and a **multi-select of rounds** populated from `interviews`, defaulting to none selected, i.e.
   "applies to the whole process". The default is the common case, so the form stays one paste and
   one save.
3. **Assistant said / they said** — for each round that has both an evaluation and covering
   feedback, a two-column block showing the evaluator's verdict next to the employer's words. Same
   pairs as §4, rendered instead of injected.
4. **Export folder** — one `InfoRow` for `export_folder` when set, so the page accounts for every
   asset the job owns.

---

## 6. Implementation steps

Each step ends green before the next starts.

1. **Storage.** `job_feedback` in `SCHEMA`; `backend/storage/feedback.py` with `add_feedback`,
   `list_feedback(journey_id)`, `list_recent_feedback(profile_id, limit, company_name="")`,
   `delete_feedback`, and `render_feedback_for_prompt(entries) -> str` (returns `""` when empty,
   mirroring `render_playbook_for_prompt`). Resolve the `PRAGMA foreign_keys` question here.
   → verify: `uv run pytest backend/tests/test_feedback_storage.py` — CRUD, profile scoping,
   empty-text rows excluded, same-company override, journey deletion removes feedback.

2. **Round-linked evaluations + calibration pairing.** The two `coaching_insights` columns and their
   `_migrate()` ALTERs; `save_coaching_insight` takes `journey_id` / `interview_id` and
   `evaluator.py:240` passes them; `list_evaluator_calibration(profile_id, limit)` and
   `render_calibration_for_prompt(pairs) -> str` in `backend/storage/feedback.py`.
   → verify: `uv run pytest backend/tests/test_evaluator_calibration.py` — `interview_ids == []`
   fans out to every evaluated round of the journey, a pinned list selects only those rounds, rounds
   with no evaluation produce no pair, pre-migration `NULL` rows are skipped, and the renderer
   returns `""` for an empty list.

3. **API.** `POST /api/journeys/{journey_id}/feedback`,
   `DELETE /api/journeys/{journey_id}/feedback/{feedback_id}`, and `interviews` + `feedback` +
   `calibration` in `journey_detail`. 404 on unknown journey; `profile_id` read from the journey;
   reject `interview_ids` entries that do not belong to this journey.
   → verify: `uv run pytest backend/tests/test_feedback_api.py`.

4. **Job detail page.** The four sections from §5.
   → verify: `npx tsc --noEmit` in `frontend/` (**not** `npm run build` — it corrupts a running dev
   server's `.next`), then add feedback to a real job in the browser and reload.

5. **Playbook extension.** `employer_feedback_themes` column + `_migrate()` ALTER, a
   `_normalize_theme_items` normaliser, rendering in `render_playbook_for_prompt`, the new key in
   `remove_playbook_item`'s allowed set, and the category in the profile page's playbook UI.
   → verify: `uv run pytest backend/tests/ -k playbook` + `npx tsc --noEmit`.

6. **Prompts + node wiring.** `generate_alignment_strategy.v3.txt`,
   `generate_interview_briefing.v5.txt`, `analyze_interview_performance.v5.txt` (+
   `interview_evaluator.system.v5.txt`), `synthesize_learning.v2.txt` (+ `.system.v2.txt`) — the
   first two and the last carrying the §3 guardrail block, the evaluator carrying the §4 framing.
   Wire the `strategy`, `interview_briefing`, `evaluator` and `synthesize_learning` nodes. Never edit
   an existing version in place. Check whether `position_candidate` also needs the variable, or
   whether alignment strategy alone is sufficient.
   → verify: `uv run pytest backend/tests/test_v2_prompts.py backend/tests/test_prompts_resolve.py`
   — each new template renders both with and without its new input, and the empty case is byte-identical
   to the previous version's output.

7. **Settings.** `feedback_window_n: int = 5` and `calibration_window_n: int = 3` on `AppSettings`.
   → verify: `uv run pytest backend/tests/test_settings_persistence.py`.

8. **Ship.** Full suite (`uv run pytest`), README + `docs/ARCHITECTURE.md` note, version bump to
   `0.11.0` in `pyproject.toml` (+ `uv lock`), `frontend/package.json`
   (+ `npm install --package-lock-only`) and `CLAUDE.md`, committed and pushed together.
   **Restart the backend** — new Python, prompt versions and settings are not hot-reloaded.

---

## 7. Conventions this touches

- Prompts are versioned; add `vN+1`, never mutate an existing file.
- LangGraph nodes return partial state dicts.
- `ApplicationState` keeps fields for all four assistants — no new state field is needed here, since
  feedback is fetched inline in the consuming nodes exactly as `cl_loop` fetches the playbook.
- Secrets stay in `.env`; `feedback_window_n` belongs in `settings.json`.

## 8. Flagged

- **Journeys with `profile_id = NULL`** store feedback but never feed learning, because every
  injection query is profile-scoped. The entries stay visible on the job page. Acceptable, but worth
  a one-line hint in the UI.
- **Overfitting to one rejection** is the main quality risk. Mitigated by the guardrail framing and
  by requiring recurrence before a theme is promoted to the playbook.
- **Rejection is not proof the interview went badly** — and the candidate cannot tell the
  difference. A performance rejection and a frozen-budget rejection arrive in the same email. The
  system therefore never asks the candidate to attribute cause, and never treats an outcome as
  evidence. Resolved structurally instead: `outcome` is excluded from the calibration payload, so
  the only thing that can teach the evaluator anything is what the employer *said about the
  candidate*. A rejection with no substantive text produces no pair, which is correct — it carries
  no information. Politeness boilerplate that names nothing specific is handled in the §4 framing.
  The residual risk is boilerplate that *sounds* specific ("we found someone whose background
  matched more closely"); the two-independent-pairs rule is what stops a single such message from
  moving anything.
- **Calibration cold-starts empty.** A pair needs a round that has both an evaluation and covering
  feedback, so expect none for the first few jobs. Both the prompt block and the job-page section
  must render nothing — not an empty heading — when there are no pairs.
- **Not in scope:** standalone feedback for applications the assistant never handled, in-session
  conversational capture, and a feedback badge on the jobs list. All are additive later.
