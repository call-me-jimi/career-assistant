"""Blind pairwise rating in the terminal: two outputs, random order, no model names."""

from __future__ import annotations

import random
from collections import defaultdict

from backend.eval import store

_RULE = "─" * 72


async def rate_run(run_id: int, limit: int | None = None, seed: int | None = None) -> int:
    run = await store.get_run(run_id)
    if not run or run["kind"] != "replay":
        raise ValueError(f"Run {run_id} is not a replay run")
    results = await store.list_results(run_id)
    a_rows: dict[int, list[dict]] = defaultdict(list)
    for r in results:
        if r["side"] == "A" and not r["error"]:
            a_rows[r["trace_id"]].append(r)
    todo = [r for r in results if r["side"] == "B" and not r["error"] and not r["human_verdict"]
            and a_rows[r["trace_id"]]]
    rng = random.Random(seed)
    rng.shuffle(todo)
    todo = todo[:limit] if limit else todo

    rated = 0
    for n, b in enumerate(todo, 1):
        a = a_rows[b["trace_id"]][b["sample"] % len(a_rows[b["trace_id"]])]
        flipped = rng.random() < 0.5
        first, second = (b, a) if flipped else (a, b)
        print(f"\n{_RULE}\nPair {n}/{len(todo)} · task {run['task']} · case {b['trace_id']}\n{_RULE}")
        print(f"\n=== Output 1 ===\n\n{first['response_text']}\n\n=== Output 2 ===\n\n{second['response_text']}\n")
        choice = ""
        while choice not in {"1", "2", "t", "s", "q"}:
            choice = input("Better: 1 / 2 / t(ie) / s(kip) / q(uit) > ").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            continue
        if choice == "t":
            verdict = "tie"
        else:
            b_won = (choice == "1") == flipped
            verdict = "win" if b_won else "loss"
        await store.update_result(b["result_id"], human_verdict=verdict)
        rated += 1
    return rated
