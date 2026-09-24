"""Score a run's outputs: deterministic metrics always, judge calls where the task needs them.

Rerunning is cheap: deterministic metrics are recomputed, judge results already
stored (verdicts, recall flags) are kept rather than paid for twice.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable

from backend.eval import store
from backend.eval.ground_truth import briefing_questions
from backend.eval.judge import Judge
from backend.eval.labels import load_label
from backend.eval.replay import confirm_spend, cost_usd, gather_limited
from backend.eval.scorers import field_prf, number_grounding, parse_json, words

# Tasks judged against labels, not against each other.
EXTRACTION_TASKS = {
    "candidate_profile", "extract_job_and_company_information", "infer_role",
    "detect_language", "synthesize_learning",
}
# Tasks that are themselves judges; their score is the metric (see judge_check.py).
SCORING_TASKS = {"simulate_hiring_manager", "analyze_interview_performance"}

_VERDICT = {"A": "loss", "B": "win", "tie": "tie"}


def base_metrics(output: str, source: str, expects_json: bool) -> dict[str, Any]:
    m: dict[str, Any] = {"words": words(output), **number_grounding(output, source)}
    parsed = parse_json(output)
    if expects_json:
        m["json_ok"] = parsed is not None
    if parsed and isinstance(parsed.get("overall_score"), (int, float)):
        m["score"] = float(parsed["overall_score"])
    return m


def _judge_estimate(judge: Judge, pairs: int, chars_per_pair: int, recall_calls: int) -> float:
    tokens_in = (pairs * 2 * chars_per_pair + recall_calls * chars_per_pair) // 4
    return cost_usd(judge.cfg.model_name, tokens_in, (pairs * 2 + recall_calls) * 150)


async def score_run(
    run_id: int, judge_spec: str | None = None, use_judge: bool = True, assume_yes: bool = False
) -> Judge | None:
    run = await store.get_run(run_id)
    if not run:
        raise ValueError(f"No run {run_id}")
    task = run["task"]
    results = await store.list_results(run_id)
    cases = {c["trace_id"]: c for c in await store.load_cases(sorted({r["trace_id"] for r in results}))}

    # Deterministic metrics for every row.
    for r in results:
        case = cases[r["trace_id"]]
        source = store.user_text(case["user_prompt"]) + "\n" + (case["system_prompt"] or "")
        expects_json = parse_json(case["response_text"] or "") is not None
        m = {**r["metrics"], **base_metrics(r["response_text"], source, expects_json)}
        label = load_label(r["trace_id"]) if task in EXTRACTION_TASKS else None
        if label and label["kind"] == "fields":
            m.update(field_prf(parse_json(r["response_text"]) or {}, label["expected"]))
        r["metrics"] = m
        await store.update_result(r["result_id"], metrics=m)

    if run["kind"] != "replay" or not use_judge:
        return None

    judge = Judge(judge_spec)
    # A stored baseline was written by whatever model the traces name — gpt-5.5 among them.
    stored = [c["model"] or "" for c in cases.values()] if run["baseline_model"] == "stored" else []
    judge.check_independent(run["baseline_model"], run["candidate_model"], *stored)
    await store.set_judge_model(run_id, judge.name)

    by_trace: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        if not r["error"] or r["error"] == "truncated":
            by_trace[r["trace_id"]][r["side"]].append(r)

    jobs: list[Callable[[], Awaitable[None]]] = []
    pairs = 0
    chars = 0

    if task not in EXTRACTION_TASKS | SCORING_TASKS:
        for trace_id, sides in by_trace.items():
            request = store.user_text(cases[trace_id]["user_prompt"])
            a_rows = sides["A"]
            for i, b in enumerate(sides["B"]):
                if b["judge_verdict"] or not a_rows:
                    continue
                a = a_rows[i % len(a_rows)]
                pairs += 1
                chars = max(chars, len(request) + len(a["response_text"]) + len(b["response_text"]))

                async def pair(b=b, a=a, request=request) -> None:
                    winner = await judge.pairwise(task, request, a["response_text"], b["response_text"])
                    await store.update_result(b["result_id"], judge_verdict=_VERDICT[winner])
                jobs.append(pair)

    recall_rows: list[tuple[dict, str, list[str]]] = []
    if task in EXTRACTION_TASKS:
        for trace_id, sides in by_trace.items():
            label = load_label(trace_id)
            if label and label["kind"] == "facts":
                recall_rows += [(r, "fact_recall", label["facts"]) for s in sides.values() for r in s]
    if task == "interview_briefing":
        truth = await briefing_questions()
        for trace_id, sides in by_trace.items():
            if trace_id in truth:
                recall_rows += [(r, "question_recall", truth[trace_id]) for s in sides.values() for r in s]

    for r, key, items in recall_rows:
        if key in r["metrics"]:
            continue
        chars = max(chars, len(r["response_text"]))

        async def recall(r=r, key=key, items=items) -> None:
            fn = judge.fact_recall if key == "fact_recall" else judge.briefing_recall
            flags = await fn(r["response_text"], items)
            if flags is not None:
                r["metrics"][key] = round(sum(flags) / len(flags), 3)
                await store.update_result(r["result_id"], metrics=r["metrics"])
        jobs.append(recall)

    if not jobs:
        return judge
    if not confirm_spend(_judge_estimate(judge, pairs, chars, len(jobs) - pairs), assume_yes,
                         f"judging with {judge.name}"):
        return judge
    await gather_limited(jobs)
    return judge
