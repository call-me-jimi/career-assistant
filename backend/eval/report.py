"""Plain-text report for a run. Every number comes with its n; small n says so."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import mean, median, pstdev
from typing import Any

from backend.eval import store
from backend.eval.ground_truth import evaluator_outcomes
from backend.eval.scorers import mean_ci, verdict, wilson

# Metrics averaged per side and compared B − A per case; True = higher is better.
NUMERIC = {
    "score": True, "precision": True, "recall": True, "fact_recall": True,
    "question_recall": True, "words": None, "ungrounded": False,
}


def _f(x: float | None, digits: int = 2) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def _metric(r: dict[str, Any], key: str) -> float | None:
    if key == "ungrounded":
        return float(len(r["metrics"]["ungrounded_numbers"])) if "ungrounded_numbers" in r["metrics"] else None
    v = r["metrics"].get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _p95(rs: list[dict]) -> float | None:
    """Nearest-rank 95th percentile of latency, in seconds."""
    if not rs:
        return None
    ms = sorted(r["duration_ms"] for r in rs)
    return ms[math.ceil(0.95 * len(ms)) - 1] / 1000


def _side_table(rows: dict[str, list[dict]], models: dict[str, str]) -> list[str]:
    out = [f"{'':24}{'A baseline':>28}{'B candidate':>28}"]

    def line(name: str, fn) -> None:
        vals = [fn(rows.get(s, [])) for s in "AB"]
        if any(v is not None for v in vals):
            out.append(f"{name:24}" + "".join(f"{v if isinstance(v, str) else _f(v):>28}" for v in vals))

    out.append(f"{'model':24}" + "".join(f"{models[s].split(':', 1)[-1][:27]:>28}" for s in "AB"))
    line("outputs", lambda rs: str(len(rs)) if rs else None)
    line("errors", lambda rs: str(sum(bool(r["error"]) for r in rs)) if rs else None)
    line("cost per call ($)", lambda rs: mean(r["cost_usd"] for r in rs) if rs else None)
    line("latency p50 (s)", lambda rs: median(r["duration_ms"] for r in rs) / 1000 if rs else None)
    line("latency p95 (s)", _p95)

    def share(key: str):
        def fn(rs: list[dict]) -> float | None:
            vals = [r["metrics"][key] for r in rs if key in r["metrics"]]
            return sum(map(bool, vals)) / len(vals) if vals else None
        return fn

    def has_ungrounded(rs: list[dict]) -> float | None:
        vals = [bool(r["metrics"]["ungrounded_numbers"]) for r in rs if "ungrounded_numbers" in r["metrics"]]
        return sum(vals) / len(vals) if vals else None

    line("valid JSON (share)", share("json_ok"))
    line("invented numbers (share)", has_ungrounded)
    for key in NUMERIC:
        def avg(rs: list[dict], key=key) -> float | None:
            vals = [v for r in rs if (v := _metric(r, key)) is not None]
            return mean(vals) if vals else None
        line(f"mean {key}", avg)
    return out


def _paired(rows: dict[str, list[dict]]) -> list[str]:
    """B − A per case (samples averaged first), so each case counts once."""
    out: list[str] = []
    for key, higher_better in NUMERIC.items():
        per_case: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for side in "AB":
            for r in rows.get(side, []):
                if (v := _metric(r, key)) is not None:
                    per_case[r["trace_id"]][side].append(v)
        diffs = [mean(s["B"]) - mean(s["A"]) for s in per_case.values() if s["A"] and s["B"]]
        ci = mean_ci(diffs)
        if not ci:
            continue
        m, lo, hi = ci
        note = ""
        if higher_better is not None and len(diffs) > 1 and (lo > 0 or hi < 0):
            better = (lo > 0) == higher_better
            note = "  candidate better" if better else "  candidate worse"
        out.append(f"  {key:20} {m:+8.2f}   95% CI [{lo:+.2f}, {hi:+.2f}]   n={len(diffs)}{note}")
    return out


def _win_rate(title: str, verdicts: list[str]) -> list[str]:
    wins, losses, ties = (verdicts.count(v) for v in ("win", "loss", "tie"))
    decided = wins + losses
    if not verdicts:
        return []
    lo, hi = wilson(wins, decided)
    rate = wins / decided if decided else None
    return [
        f"{title}: {wins} wins / {ties} ties / {losses} losses for the candidate",
        f"  win rate (ties excluded) {_f(rate)}   95% CI [{lo:.2f}, {hi:.2f}]   n={decided}"
        f"   → {verdict(lo, hi)}",
    ]


async def replay_report(run: dict, results: list[dict]) -> list[str]:
    rows: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        rows[r["side"]].append(r)
    models = {"A": run["baseline_model"], "B": run["candidate_model"]}
    out = _side_table(rows, models)
    paired = _paired(rows)
    if paired:
        out += ["", "Candidate minus baseline, per case:"] + paired
    for side in "AB":
        flagged = Counter(n for r in rows.get(side, []) for n in r["metrics"].get("ungrounded_numbers", []))
        if flagged:
            top = ", ".join(f"{n}×{c}" if c > 1 else n for n, c in flagged.most_common(12))
            out.append(f"\nNumbers in {side} not found in the input (check: invented, or just advice?): {top}")
    b = rows.get("B", [])
    judged = [r["judge_verdict"] for r in b if r["judge_verdict"]]
    human = [r["human_verdict"] for r in b if r["human_verdict"]]
    for title, vs in (("Judge " + (run["judge_model"] or ""), judged), ("Your blind ratings", human)):
        if vs:
            out += [""] + _win_rate(title, vs)
    both = [r for r in b if r["judge_verdict"] and r["human_verdict"]]
    if both:
        agree = sum(r["judge_verdict"] == r["human_verdict"] for r in both) / len(both)
        warn = "  (below 0.70: treat the judge as advisory)" if agree < 0.7 else ""
        out.append(f"\nJudge agrees with you on {agree:.0%} of {len(both)} pairs{warn}")
    return out


async def judge_check_report(run: dict, results: list[dict]) -> list[str]:
    outcomes = await evaluator_outcomes() if run["task"] == "analyze_interview_performance" else {}
    out: list[str] = []
    for side, model in (("A", run["baseline_model"]), ("B", run["candidate_model"])):
        rows = [r for r in results if r["side"] == side]
        if not rows:
            continue
        scores: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for r in rows:
            if (s := _metric(r, "score")) is not None:
                scores[r["trace_id"]][r["variant"]].append(s)
        unparsed = sum(_metric(r, "score") is None for r in rows)
        out += [f"{side}  {model}", f"  outputs {len(rows)}, without a score {unparsed}"]

        spreads = [pstdev(v["original"]) for v in scores.values() if len(v["original"]) > 1]
        if spreads:
            out.append(f"  consistency: mean score std-dev {mean(spreads):.2f} over {len(spreads)} inputs"
                       " (0 = same score every time)")

        per_variant: dict[str, list[bool]] = defaultdict(list)
        for v in scores.values():
            if not v["original"]:
                continue
            base = mean(v["original"])
            for name, vals in v.items():
                if name != "original":
                    per_variant[name] += [s < base for s in vals]
        if per_variant:
            flat = [x for xs in per_variant.values() for x in xs]
            lo, hi = wilson(sum(flat), len(flat))
            out.append(f"  discrimination: degraded letter scored lower in {sum(flat)}/{len(flat)}"
                       f" = {sum(flat) / len(flat):.0%}   95% CI [{lo:.0%}, {hi:.0%}]   target ≥ 90%")
            for name, xs in sorted(per_variant.items()):
                out.append(f"    {name:18} {sum(xs)}/{len(xs)}")

        if outcomes:
            groups: dict[str, list[float]] = defaultdict(list)
            for trace_id, v in scores.items():
                if trace_id in outcomes and v["original"]:
                    groups[outcomes[trace_id]].append(mean(v["original"]))
            adv, rej = groups.get("advanced", []), groups.get("rejected", [])
            gap = mean(adv) - mean(rej) if adv and rej else None
            out.append(f"  separation: advanced {_f(mean(adv) if adv else None)} (n={len(adv)})"
                       f" vs rejected {_f(mean(rej) if rej else None)} (n={len(rej)}), gap {_f(gap)}")
        out.append("")
    return out


async def render(run_id: int) -> str:
    run = await store.get_run(run_id)
    if not run:
        raise ValueError(f"No run {run_id}")
    results = await store.list_results(run_id)
    cases = len({r["trace_id"] for r in results})
    head = [
        f"Run {run_id} · {run['kind']} · task {run['task']} · set {run['set_name']}",
        f"{cases} cases × {run['samples']} samples",
        "",
    ]
    body = await (judge_check_report if run["kind"] == "judge-check" else replay_report)(run, results)
    if cases < 10:
        body.append(f"\nOnly {cases} cases: expect wide intervals; treat small differences as noise.")
    return "\n".join(head + body)
