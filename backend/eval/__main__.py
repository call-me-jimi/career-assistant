"""uv run python -m backend.eval <command> — see docs/evaluation.md."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt

from backend.eval import store
from backend.eval.ground_truth import briefing_questions, evaluator_outcomes
from backend.eval.judge_check import run_judge_check
from backend.eval.labels import init_labels
from backend.eval.rate import rate_run
from backend.eval.replay import STORED, run_replay
from backend.eval.report import render
from backend.eval.score import score_run
from backend.storage.db import init_db


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m backend.eval", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set", help="create or list frozen input sets")
    s_sub = s.add_subparsers(dest="set_cmd", required=True)
    c = s_sub.add_parser("create", help="freeze the newest traces of a task as a named set")
    c.add_argument("--name", required=True)
    c.add_argument("--task", required=True)
    c.add_argument("--last", type=int, default=20, help="how many cases (default 20)")
    c.add_argument("--model", help="only traces whose model contains this text")
    c.add_argument("--prompt-version", help="only traces of this template, e.g. generate_cover_letter.v8")
    c.add_argument("--all-calls", action="store_true",
                   help="every call, not just the first per session")
    c.add_argument("--ground-truth-only", action="store_true",
                   help="interview_briefing / analyze_interview_performance: only cases whose "
                        "real interview questions or outcome are known")
    s_sub.add_parser("list")

    r = sub.add_parser("run", help="replay a set against a candidate model")
    r.add_argument("--set", required=True)
    r.add_argument("--candidate", required=True, help="model, e.g. claude-opus-5-5 or ollama:llama3.1")
    r.add_argument("--baseline", default=STORED,
                   help="model to rerun as the baseline; default: the stored traced output")
    r.add_argument("--samples", type=int, default=3)
    r.add_argument("--yes", action="store_true", help="skip the cost confirmation")

    sc = sub.add_parser("score", help="compute metrics and judge verdicts for a run")
    sc.add_argument("--run", type=int, required=True)
    sc.add_argument("--judge", help="judge model; default settings.eval_judge_llm")
    sc.add_argument("--no-judge", action="store_true", help="deterministic metrics only")
    sc.add_argument("--yes", action="store_true")

    j = sub.add_parser("judge-check", help="consistency / discrimination of the app's judges")
    j.add_argument("--set", required=True)
    j.add_argument("--models", nargs="+", required=True, help="one or two models")
    j.add_argument("--samples", type=int, default=5)
    j.add_argument("--yes", action="store_true")

    ra = sub.add_parser("rate", help="blind-rate pairs of a run yourself")
    ra.add_argument("--run", type=int, required=True)
    ra.add_argument("--limit", type=int)

    rp = sub.add_parser("report", help="print a run's report")
    rp.add_argument("--run", type=int, required=True)

    sub.add_parser("runs", help="list runs")

    lb = sub.add_parser("labels", help="write draft labels for an extraction set")
    lb.add_argument("--set", required=True)
    return p


async def main(args: argparse.Namespace) -> None:
    await init_db()
    if args.cmd == "set" and args.set_cmd == "create":
        ids = await store.pick_traces(args.task, 10**6 if args.ground_truth_only else args.last,
                                      args.model, not args.all_calls, args.prompt_version)
        if args.ground_truth_only:
            known = await (briefing_questions() if args.task == "interview_briefing"
                           else evaluator_outcomes())
            ids = [i for i in ids if i in known][-args.last:]
        if not ids:
            raise SystemExit(f"No replayable traces for task {args.task!r}")
        await store.create_set(args.name, args.task, ids)
        print(f"Set {args.name!r}: {len(ids)} cases of {args.task}")
    elif args.cmd == "set":
        for s in await store.list_sets():
            print(f"{s['name']:24} {s['task']:36} {len(s['trace_ids']):4} cases")
    elif args.cmd == "run":
        run_id = await run_replay(args.set, args.candidate, args.baseline, args.samples, args.yes)
        if run_id:
            print(f"Run {run_id} done. Next: python -m backend.eval score --run {run_id}")
    elif args.cmd == "score":
        judge = await score_run(args.run, args.judge, not args.no_judge, args.yes)
        if judge:
            print(f"Judge {judge.name} spent ${judge.spent_usd:.2f}")
        print(await render(args.run))
    elif args.cmd == "judge-check":
        run_id = await run_judge_check(args.set, args.models, args.samples, args.yes)
        if run_id:
            await score_run(run_id, use_judge=False)
            print(await render(run_id))
    elif args.cmd == "rate":
        print(f"Rated {await rate_run(args.run, args.limit)} pairs")
    elif args.cmd == "report":
        print(await render(args.run))
    elif args.cmd == "runs":
        for r in await store.list_runs():
            when = dt.datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d %H:%M")
            print(f"{r['run_id']:4}  {when}  {r['kind']:11} {r['task']:32} "
                  f"{r['baseline_model']} → {r['candidate_model']}  set={r['set_name']}")
    elif args.cmd == "labels":
        paths = await init_labels(args.set)
        print(f"Wrote {len(paths)} draft labels; edit them before scoring:")
        for path in paths:
            print(f"  {path}")


if __name__ == "__main__":
    asyncio.run(main(_parser().parse_args()))
