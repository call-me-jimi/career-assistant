# Evaluating models and prompts

How to tell whether a model switch (say Opus 4.8 → Opus 5.5) or a new prompt version makes an
assistant better, task by task, using the calls you have already made.

The harness lives in `backend/eval/` and runs from the command line. It never touches a session:
it reads past LLM calls from the `traces` table, sends the same prompts to another model, and
scores both sets of outputs. Results go into three tables in the same SQLite database
(`eval_sets`, `eval_runs`, `eval_results`).

> **Your data stays local.** Eval sets are built from your real CV, job ads and interviews. The
> tables and label files live under `backend/data/`, which is git-ignored. The only thing that
> leaves your machine is the replayed prompts, sent to the providers you pick — the same as
> using the app.

## The idea in one paragraph

Employer outcomes are too few, too slow and too confounded to tell two models apart. So each task
gets the cheapest trustworthy proxy instead. **Replay** holds the input fixed: every past call's
exact system and user prompt is sent to the candidate model, so any difference comes from the
model. **Scorers** turn outputs into numbers. They use hand-checked labels for extraction, a
check that every number in the output appears in the input, a pairwise LLM judge for generated
text, and the questions actually asked in your real interviews for briefings. **Your own blind
ratings** are the final word on anything subjective.

## Quick start: is Opus 5.5 better at cover letters?

```bash
# 1. Freeze 20 past cover-letter calls as a named set (first call of each session)
uv run python -m backend.eval set create --name letters-20 --task cover_letter_generation --last 20

# 2. Replay them on the candidate, 3 samples each; the stored output is the baseline
uv run python -m backend.eval run --set letters-20 --candidate claude-opus-5-5 --samples 3

# 3. Score: deterministic metrics + the pairwise judge (asks before spending over the cap)
uv run python -m backend.eval score --run 1

# 4. Rate ~20 pairs yourself, blind
uv run python -m backend.eval rate --run 1 --limit 20

# 5. Read the verdict
uv run python -m backend.eval report --run 1
```

Each run prints its estimated cost first. Above `eval_max_usd` (default $5, in `settings.json`)
it asks before continuing; `--yes` skips the question.

## Commands

| Command | What it does |
| --- | --- |
| `set create --name N --task T [--last 20] [--model substr] [--prompt-version V] [--all-calls] [--ground-truth-only]` | Freezes the newest replayable traces of a task into a named set. By default, one case per session (the first call), so a three-round letter loop counts once. `--ground-truth-only` keeps only briefings whose real interview questions are known, or evaluations whose round outcome is known. |
| `set list` | Lists the sets. |
| `run --set N --candidate M [--baseline M] [--samples 3]` | Replays the set on `M`. Without `--baseline`, the stored output is side A (free, but one sample). Pass `--baseline claude-opus-4-8` to rerun the old model too, when its traces are from an older prompt version or you want samples on both sides. |
| `score --run R [--judge M] [--no-judge]` | Computes metrics and, where the task needs it, judge verdicts. Safe to rerun: stored verdicts and recall flags are reused, not paid for again. |
| `judge-check --set N --models M [M2] [--samples 5]` | Tests the app's own judges (the hiring-manager simulator and the interview evaluator). See below. |
| `labels --set N` | Writes draft labels for an extraction set, for you to correct. |
| `rate --run R [--limit 20]` | Shows you two outputs at a time, in random order, with no model names. You pick 1, 2 or tie. |
| `report --run R` | Prints the report again. |
| `runs` | Lists all runs. |

**Model names**: `claude-*` and `gpt-*` are recognised. Anything else is written as
`provider:model`, e.g. `ollama:llama3.1` or `openai:o4-mini`.

## What each task is scored on

| Tasks | How they're scored | Where the truth comes from |
| --- | --- | --- |
| `candidate_profile`, `extract_job_and_company_information`, `infer_role`, `detect_language`, `synthesize_learning` | JSON outputs: field-level **precision and recall** against a label. Prose outputs: **fact recall**, the share of your listed facts the output states (the judge checks). | Labels you write once (see below). |
| `interview_briefing` | **Pairwise win rate**, plus **question recall**: the share of the questions actually asked in the real interview that the briefing prepared you for. | The evaluator's per-question breakdown of the recording of that round, matched automatically. |
| `cover_letter_generation`, `refine_cover_letter`, `alignment_strategy`, `position_candidate`, `qa`, `career_advisor_swot`, … | **Pairwise win rate** from the judge and from your blind ratings. | Your judgement. |
| `simulate_hiring_manager`, `analyze_interview_performance` | Their score, with consistency, discrimination and separation from `judge-check`. | Deliberately degraded letters; round outcomes. |
| Every task | Cost per call, p50/p95 latency, errors, valid JSON, word count, **invented numbers**. | The input prompt. |

**Invented numbers** are numbers in the output that never appear in the input: team sizes,
percentages, revenue, years. It is the cheapest reliable sign of a made-up fact. "€500k",
"500.000" and "500,000" count as the same number. Some flags are advice rather than a claimed fact
("rehearse it in 30–45 seconds"), so the report lists the flagged numbers for you to check.

## Reading the report

```
                               A baseline                 B candidate
model                              stored             claude-opus-5-5
cost per call ($)                    0.13                        0.09
invented numbers (share)             0.10                        0.05
…
Candidate minus baseline, per case:
  words                  +58.50   95% CI [+12.10, +104.90]   n=20
Judge openai:gpt-5.5: 31 wins / 9 ties / 20 losses for the candidate
  win rate (ties excluded) 0.61   95% CI [0.47, 0.73]   n=51   → inconclusive
Your blind ratings: 12 wins / 3 ties / 5 losses …
Judge agrees with you on 75% of 20 pairs
```

- **Verdict**: `switch` when the whole 95% interval of the win rate is above 0.5, `keep` when it
  is below, otherwise `inconclusive`. With about 20 cases only large differences show up. Say
  "inconclusive" out loud rather than reading tea leaves.
- **Per-case differences** average each case's samples first, so every job counts once.
  "candidate better/worse" appears only when the interval excludes zero.
- **Judge vs you**: if the judge agrees with your blind ratings on fewer than 70% of pairs, the
  report marks the judge as advisory. Trust your ratings.

## The judge

Pairwise comparisons and recall checks use one fixed judge model per run: `eval_judge_llm` in
`backend/config/settings.json` (default `openai:gpt-5.5`), or `--judge` on `score`. The rules:

- **It never judges its own model.** `score` refuses if the judge is the baseline, the candidate,
  or the model that wrote any stored baseline output. Models favour their own writing. Some older
  cover letters were written by `gpt-5.5`, so a set containing them needs another judge.
- **Every pair is judged twice, with the order swapped.** A preference counts only if it survives
  the swap; otherwise it is a tie. This cancels the judge's position bias.
- **Keep the judge fixed across runs you compare.** Change it and older win rates are no longer
  comparable.

The judge prompts are ordinary versioned templates: `eval_pairwise`, `eval_briefing_recall` and
`eval_fact_recall` under `backend/templates/`.

## Labels for extraction tasks

```bash
uv run python -m backend.eval set create --name profiles --task candidate_profile --last 10
uv run python -m backend.eval labels --set profiles
```

This writes one draft file per case to `backend/data/eval/labels/<trace_id>.json`:

- **JSON outputs** become `{"kind": "fields", "expected": {…}}`, seeded with what the old model
  extracted. Correct the wrong values and delete what shouldn't be there. Scoring is field
  precision/recall; list order and case don't matter.
- **Prose outputs** (the candidate profile is markdown) become
  `{"kind": "facts", "facts": [], "reference_output": "…"}`. Write the 5–15 facts a correct
  answer must state, e.g. `"Led a team of 9 with 6 direct reports"`. A label with an empty fact
  list is ignored.

`extract_job_and_company_information` covers two different calls: the job-ad extraction (JSON)
and the company-research summary (prose). A set of that task gets both kinds of label.

Label once; every later run on that set reuses them. About 15 labels is enough for a first
verdict.

## Testing the judges themselves

The hiring-manager simulator and the interview evaluator are judges too. If they can't tell good
from bad, the cover-letter loop optimises noise. `judge-check` measures three things:

```bash
uv run python -m backend.eval set create --name hm-10 --task simulate_hiring_manager --last 10
uv run python -m backend.eval judge-check --set hm-10 --models claude-opus-4-8 claude-opus-5-5 --samples 5
```

- **Consistency**: the same input scored N times. The mean standard deviation should be well
  under one point.
- **Discrimination** (hiring manager only): each letter is scored next to four mechanically
  worse copies. `drop_evidence` removes the paragraph with the most numbers, `generic_opening`
  swaps in a boilerplate opening, `truncated` cuts the letter in half, and `wrong_number` changes
  a figure so it contradicts the CV. A good judge scores every one lower; the target is at least
  90%. The per-degradation breakdown shows what a model misses.
- **Separation** (interview evaluator): its mean score on rounds that advanced against rounds
  that were rejected, for sets built with `--ground-truth-only`. It's the same question the
  Learned page asks. Most known outcomes are rejections, so read the gap together with its n.

## Comparing prompt versions

Every trace records the template that produced it (`traces.prompt_version`, e.g.
`generate_cover_letter.v8`; empty for calls made before v0.20.0). Change one thing at a time:

- **New model, same prompt**: pin the set to one template, so a prompt bump in the middle of
  your history doesn't blur the comparison:
  `set create --name letters-v8 --task cover_letter_generation --prompt-version generate_cover_letter.v8`.
- **New prompt, same model**: not automated yet. Replay sends the *stored* prompt text, so a new
  template can't be applied to old traces. The inputs it needs (CV, job, strategy) are rendered
  away by then. Until then, compare prompt versions in normal use with the dashboard, and use
  `--prompt-version` to keep them apart in sets.

## Limits

- Replay is per call, not end to end. A worse extraction feeding a worse letter isn't captured;
  score the extraction task directly.
- Only single-turn calls replay. Chat tasks with history (`career_advisor_chat`) are skipped
  when a set is built.
- Question recall and separation depend on interviews you have both prepared and evaluated. The
  set grows as you use the Interview Evaluator.
- Callback rate is deliberately not a metric: too sparse and too confounded to separate models.
