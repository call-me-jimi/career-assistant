# Plan — From one application to a whole search

**Goal.** The app stops being a tool you point at a single application and becomes the place a
job search is run: every application tracked, every outcome captured where it happens, and the
learning loop visible enough that "the assistants get better with every rejection" is something
the user can see rather than something we assert.

Status: planned, not implemented. Target release: `v0.13.0`.

Design mocks: `docs/plans/whole-search-flows.html` (five flows, drawn against live data).

---

## 1. What exists today

| Concern | Where | Gap |
| --- | --- | --- |
| Landing | `frontend/app/page.tsx` | "Three stages of one application" — a tool rack; the search is invisible |
| Tracker table | `frontend/app/jobs/page.tsx` | Editable dates, but no sort, no grouping, status column repeats 51× |
| Job detail | `frontend/app/jobs/[id]/page.tsx` | Read-only; its `Interview` type has no `scheduled_at`, so it renders `created_at` |
| Feedback capture | `/jobs/[id]`, bottom of page | Six steps and two pages from the moment a rejection arrives |
| Outcome | `job_journeys` dates **and** `job_feedback.outcome` | Two stored facts, nothing reconciles them |
| Resume a job | `select_journey` numbered chat picker | Duplicates the table you were just looking at, capped at 10 |
| Learning | `profile_playbook` → prompts | Works, but invisible; `employer_feedback_themes` is `[]` on all three profiles |
| Dashboard | `frontend/app/dashboard/page.tsx` | Answers "how much did the LLM cost", not "how is the search going" |

The backend loop is real. What is missing is capture cheap enough to feed it and a surface that
shows it working. **2 feedback entries across 51 applications** is the number this plan exists to
change.

---

## 2. Decisions already taken

These were settled during design review. They are constraints, not options.

| Decision | Consequence |
| --- | --- |
| Dates own the outcome | `job_feedback.outcome` stops being user input; derived at write time |
| A rejection carries **one** date | No `said_at` column. Recency uses `created_at` as today |
| Silence is informational | Derived from elapsed time; no `closed_at`, no bulk write-off |
| Withdrawal is the only tracked exit | `dropped_at` covers both withdrawing and giving up |
| Counters are pooled | One set of six numbers across all profiles |
| Landing stays a launcher | Assistants + counters only; no record-keeping CTAs there |
| Learnings are profile-specific until promoted | Per-item `shared` flag; nothing crosses by default |
| Promotion offers a re-run | Costed confirm; **sharing is one-way** |
| Quiet threshold is configurable | `settings.json` |
| Collapsed groups are remembered | `localStorage` |
| Assistants launched from a row skip the pickers | `journey_id` / `profile_id` / `interview_id` on session start |

---

## 3. Data model

### 3.1 `job_feedback.outcome` becomes derived

No schema change. The column stays; it stops being a parameter.

```python
# backend/storage/feedback.py
_STATUS_TO_OUTCOME = {
    "rejected": "rejected",
    "offer": "offer",
    "dropped": "withdrawn",
}

async def add_feedback(*, journey_id, profile_id, interview_ids=None,
                       stage="unknown", source="", feedback_text="") -> str:
    """`outcome` is no longer a parameter — it is read from derive_status() at
    write time, so it can never disagree with the dates."""
```

Anything not in the map (`applied`, `in_progress`, `silent`, `on_hold`, `draft`) writes `""` —
feedback recorded mid-process, before any outcome exists. `OUTCOMES` gains `""`; `ghosted` stays
in the constant for old rows but is never written again.

**Migration.** Existing rows keep their values. Two rows exist (DKB, voize), both `rejected`, both
on journeys with `rejected_at` set — already consistent. No backfill needed; assert it in a test.

### 3.2 `profile_playbook` items gain `shared`

No schema change — the columns are JSON arrays. Each item dict gains `"shared": bool`, defaulting
to `false`. `_normalize_theme_items()` and the sibling normalisers in
`backend/storage/playbook.py` must preserve it and default it when absent, exactly as they already
coerce bare strings.

Reading for a prompt becomes own-items plus every other profile's shared items:

```python
async def render_playbook_for_prompt(playbook: dict, *, shared: list[dict] | None = None) -> str
async def list_shared_items(exclude_profile_id: str) -> dict[str, list[dict]]
```

### 3.3 `settings.json`

```json
"quiet_after_days": 30
```

Drives one counter, one filter chip and one group heading, so moving it moves all three.

### 3.4 Not added

`closed_at`, `said_at`, a `status` column, a `shared_playbook` table. Each was considered and
rejected above.

---

## 4. Status derivation gains a clock

`derive_status()` in `backend/storage/journeys.py` currently reads five dates plus
`job_interviews.scheduled_at`. It gains one rung and one argument.

```python
def derive_status(journey, interviews, *, now: float | None = None) -> str:
    ...
    if last_round is not None:
        return "in_progress"
    if journey.get("applied_at"):
        quiet_for = (now or time.time()) - last_contact_at(journey, interviews)
        if quiet_for > settings.quiet_after_days * 86400:
            return "silent"
        return "applied"
    return "draft"
```

`silent` refines **`applied` only**. An `in_progress` journey has rounds behind it and stays
in progress however long it has been quiet — see §12.

```python
def last_contact_at(journey, interviews, events=(), feedback=()) -> float | None:
    """The most recent moment anything happened: applied, a round, a logged event,
    or something an employer said. Drives both `silent` and the Waiting column."""
```

**This changes an invariant in `CLAUDE.md`.** The line currently reads "first match wins" over
five stored dates; it must say that status is a function of the stored dates *and the current
time*, and that the clock is injectable. Every existing `derive_status()` test must pass an
explicit `now` or it will go flaky the day a fixture crosses 30 days.

---

## 5. Capture — the row menu and its panels

The single highest-leverage change. Everything else is a nicer shell around the same empty
playbook if this does not land.

### 5.1 The menu

Two groups, and the split is load-bearing: the first group starts an assistant (costs an LLM
call), the second only writes a date (does not).

| Group | Item | Effect |
| --- | --- | --- |
| Work on it | *computed label* | Resume the cover-letter graph — §7 |
| | Prep for a round ▸ | Submenu of scheduled rounds, or "a round not listed" |
| | Evaluate a round ▸ | Same submenu |
| Just for the record | Schedule an interview | `POST /journeys/{id}/interviews` |
| | Log a rejection | `POST /journeys/{id}/outcome` |
| | Log an offer | `POST /journeys/{id}/outcome` |
| | Put on hold | `POST /journeys/{id}/outcome` |
| | Withdraw | `POST /journeys/{id}/outcome` |
| | Open full detail | `/applications/{id}` |
| | Delete from record | `DELETE /journeys/{id}` |

The first item's label comes from `_continue_phase()` (`backend/agent/nodes/select_journey.py:53`),
which already computes it:

| Journey state | Label |
| --- | --- |
| no `company_description` | Research the company |
| no `positioning_strategy` / `alignment_strategy` | Work out the angle |
| no `cover_letter` | Write the cover letter |
| otherwise | Revise the cover letter |

### 5.2 One atomic endpoint for outcomes

```
POST /api/journeys/{journey_id}/outcome
{
  "kind": "rejected" | "offer" | "on_hold" | "withdrawn",
  "date": 1758153600.0,
  "feedback_text": "",       # optional
  "source": "hiring_manager" # optional
}
→ 200 the full journey, status recomputed
```

Writes the date **and** the feedback row in one transaction. This is what makes §3.1 safe: the
outcome snapshot cannot be taken before the date exists, because the same call writes both.

`kind` maps to the column: `rejected→rejected_at`, `offer→offer_at`, `on_hold→on_hold_at`,
`withdrawn→dropped_at`. `stage` on the feedback row is inferred from how far the rounds got
(`unknown` when there are none). The existing `POST /journeys/{id}/feedback` stays for feedback
recorded mid-process from the timeline.

`PATCH /api/journeys/{id}` keeps accepting raw dates — the detail page and the importer use it.

### 5.3 What the user sees after saving

The confirmation names what changed in the playbook: which themes were reinforced, which are new,
and which profile they landed on. This is the only moment the product can demonstrate its thesis,
and today it is a silent database write with no screen at all.

Requires the synthesis result to be returned from the write path rather than fired and forgotten —
check whether `synthesize_learning` can run inline here or whether the panel polls.

---

## 6. The applications page

`/jobs` → `/applications`, with `/jobs` kept as a redirect. Nav label `Jobs` → `Applications`.

- **Grouped by status.** In progress · Applied, no reply yet · Open over N days · On hold ·
  Rejected · Withdrawn. Quiet groups start collapsed; state persists in `localStorage`.
- **Status column removed.** The group heading is the status.
- **`Waiting` column added** — `now - last_contact_at`, the derived number the groups sort by.
- **Sort control** — last contact, applied date, company, waiting. None exists today.
- **Search** extends to events and feedback text, not just title/company/location/notes.
- **Filter chips** mirror the six landing counters.

At 112 applications this renders nine rows: the page grows with the *live* set, not the pile.

`GET /api/journeys` gains `status`, `last_contact_at` and `waiting_days` per row. Grouping is
client-side; the API stays a flat list.

### Landing counters

```
GET /api/journeys/summary
→ { "total": 51, "in_progress": 7, "quiet": 27, "on_hold": 2,
    "rejected": 9, "withdrawn": 3 }
```

Pooled across profiles. Each counter links to `/applications` with that filter applied. Note the
six do not partition the set — `applied` under the quiet threshold belongs to none of them. That
is intentional; they are landmarks, not a census.

---

## 7. Pre-seeded assistant launches

Today every session runs `greeting → load_coaching_history → cv_intake → select_journey → …` and
stops at the numbered chat picker to ask which job — the one the user just clicked.

```python
class StartSessionPayload(BaseModel):
    assistant_type: str = "cover_letter"
    language: str = "English"
    profile_id: str | None = None      # new
    journey_id: str | None = None      # new
    interview_id: str | None = None    # new
```

When `journey_id` is present, the runner seeds `ApplicationState` from the journey using the
existing `_SEED_FIELDS` tuple and sets `phase` from `_continue_phase(assistant_type, journey)`.
`cv_intake` already no-ops when `profile_id` is set. `select_journey` gains an early return:

```python
if state.journey_id:
    return {"phase": _continue_phase(state.assistant_type, journey)}
```

Landing nodes, with a round supplied:

| Assistant | Lands on |
| --- | --- |
| Cover Letter | `research_company` / `classify_flow` / `strategy` / `cl_loop` |
| Interview Prep | `interview_context` (or `research_company` if unresearched) |
| Interview Evaluator | the recording upload, `select_interview` skipped |

`_continue_phase()` already returns exactly this. It simply never runs, because `select_journey`
interrupts first.

---

## 8. Job page — one timeline

`/applications/{id}`, replacing both `/jobs/[id]` and the table drawer.

Three tabs: **Timeline** · **Artifacts** · **Posting**.

- **Timeline** interleaves applied, rounds, events and feedback in date order. A quote sits on the
  day it was said, attached to the outcome it explains. Inline "add a note, a round, or what
  someone told you" at the foot.
- **Artifacts** lists cover letter, briefings and evaluations, each with a **provenance chip** —
  *"Shaped by 3 employer notes & 7 playbook rules"* — expandable to the quotes and their source
  jobs. Evaluations that disagreed with the outcome link to the comparison.
- **Posting** is the existing job-ad, screenshot and strategy blocks.

Header carries the profile: `CV: Head of Data`, editable, because it decides which playbook
shaped everything below and which playbook this rejection teaches.

Actions: on hold, withdraw, duplicate, delete.

**Bug fixed here.** The detail page's `Interview` type has no `scheduled_at` and renders
`created_at` — the moment the tool made the row, not when the interview happened. A single
chronology makes this impossible to ship again.

### Duplicate

```
POST /api/journeys/{id}/duplicate → the new journey
```

Copies posting, company description, location, profile and notes. Leaves dates, artifacts and
feedback behind. The new journey's cover-letter generation then sees the old rejection —
**already implemented**: `list_recent_feedback()` (`backend/storage/feedback.py:110`) always
includes same-company entries regardless of the window and sorts them first. No caller passes
`company_name`. Fixing that is three one-line changes:

- `backend/agent/nodes/cl_loop.py` — currently passes no employer feedback at all
- `backend/agent/nodes/interview_briefing.py:21`
- `backend/agent/nodes/synthesize_learning.py:138`

Simon Kucher and Jupus each appear twice in the current data.

---

## 9. Learned

`/dashboard` → `/learned`. Cost and token stats move under Settings, where they stop competing
with the search for attention.

- **Filter by profile** — Head of Data (9) · Head of AI (2) · Head of Data in Biotech (0) ·
  Shared (3).
- **Themes with evidence.** Every theme carries its quotes and the jobs they came from. A theme
  you cannot trace is a theme you will not promote.
- **Promote** — a per-item toggle writing `shared: true`.
- **Calibration.** Mean evaluator score on rounds that advanced vs rounds that were rejected.
  `list_evaluator_calibration()` already assembles the pairs; this is an aggregate over them.

### Promotion, precisely

Two distinct mechanisms, and conflating them is the easy mistake:

1. **`shared: true`** — the item is rendered into every profile's prompt from now on. Immediate,
   free, and reversible: unsetting it stops the injection.
2. **The optional re-run** — `POST /api/profiles/{id}/playbook/resynthesize` re-runs
   `synthesize_learning` for the *other* profiles so they can reconcile the new input with their
   own themes, in their own words. Costs LLM calls; the confirm names the price using the existing
   per-model pricing table.

**Sharing is one-way** in exactly this sense: (1) can be undone, (2) cannot. Once another
profile's synthesis has absorbed the item, the text is written there. Un-sharing stops it
spreading further; it does not reach back in. The confirm must say so.

---

## 10. Implementation steps

Ordered by risk, not by ease. Phases 2–5 are pleasant to build; phase 1 decides whether any of it
works.

**Phase 1 — capture.** `POST /journeys/{id}/outcome`; `add_feedback()` loses its `outcome`
parameter; the row menu and its five panels; the post-save playbook delta.
*Verify:* log a rejection with a reason in one interaction; confirm `rejected_at`, the feedback
row and its derived outcome all agree; existing 350 tests green.

**Phase 2 — the table.** `derive_status()` clock + `silent`; `last_contact_at()`;
`quiet_after_days` in settings; grouping, Waiting, sort, persisted collapse; `/journeys/summary`
and the landing strip.
*Verify:* seed 112 journeys in a test DB, confirm nine rows render; `derive_status()` tests pass
an explicit `now`.

**Phase 3 — pre-seeded launches.** Session payload fields; `select_journey` early return; menu
submenus of scheduled rounds.
*Verify:* launch Interview Prep from a row and land on `interview_context` with no picker; same
for the evaluator.

**Phase 4 — the job page.** Timeline merge; `scheduled_at` in the detail type; hold/withdraw/
delete/duplicate; profile in the header; provenance chips.
*Verify:* a round created in the table shows its scheduled date on the detail page — the current
bug, as a regression test.

**Phase 5 — learned.** `shared` flag through the normalisers; `list_shared_items()`; the page;
promotion and the costed re-run; calibration aggregate.
*Verify:* an item shared on one profile appears in another profile's rendered playbook without a
re-run.

Each phase is independently shippable and leaves the app working.

---

## 11. Conventions this touches

- **Prompts are versioned.** Most of this needs no new template: `render_playbook_for_prompt()`
  changes its *output*, not its variable, and passing `company_name` changes no text at all. Only
  `synthesize_learning` needs `v3` templates, to teach it about shared items.
- **LangGraph nodes return partial state dicts** — the `select_journey` early return is one.
- **Side effects before `interrupt()` replay on resume.** The outcome write in §5.2 is an API call,
  not a node, so it is unaffected — keep it that way.
- **`ApplicationState` keeps fields for all four assistants.** No new field needed; `journey_id`
  and `profile_id` already exist.
- **Secrets stay in `.env`**; `quiet_after_days` belongs in `settings.json`.
- **Restart the backend** after the settings and schema changes — uvicorn will not pick them up.
- **Version bump** in `pyproject.toml`, `frontend/package.json` and `CLAUDE.md` together, then
  push immediately.

---

## 12. Flagged

- **Cold start is the whole risk.** 2 feedback entries across 51 applications. The Learned page
  renders nearly empty until phase 1 changes user behaviour. Do not reorder the phases.
- **`silent` refines `applied` only.** An `in_progress` journey that has been quiet for 60 days
  still reads "In progress". That matches the mock and the counter's label, but it means a dead
  late-stage process hides in the live group. Revisit once there is a month of real data.
- **The counters do not sum to the total** — `applied` under the threshold is in none of them.
  Intentional, but it will look like a bug to anyone who adds them up.
- **`derive_status()` becomes time-dependent**, so a row's status changes overnight with nothing
  written. Fine while status is never stored; it would be a drift bug the moment anyone caches it.
- **Journeys with `profile_id = NULL`** still store feedback that never reaches learning, because
  every injection query is profile-scoped. Unchanged by this plan; the hint on the feedback form
  stays.
- **The importer backfills `created_at = now`.** `backend/tools/import_tracker_csv.py` will make
  six months of historical rejections look like this week's news to the recency window. Acceptable
  at two entries; reconsider before a large import.
- **`next_step` / `next_step_at` stay unused.** They exist in the schema and nothing reads them.
  Left alone deliberately rather than built into reminders, which were explicitly not wanted.
- **Not in scope:** response-rate analytics by source or profile, per-profile funnels,
  conversational capture, notifications of any kind.
