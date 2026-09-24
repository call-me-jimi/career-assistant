"""Test the app's own judges: the hiring-manager simulator and the interview evaluator.

Three questions, answered per model:
  consistency     — the same input scored N times: how far do the scores spread?
  discrimination  — a cover letter made deliberately worse must score lower
                    (simulate_hiring_manager only; transcripts can't be degraded cleanly)
  separation      — evaluator scores on rounds that advanced vs rounds that were
                    rejected (analyze_interview_performance, from ground_truth)
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

from backend.eval import store
from backend.eval.replay import (
    call_case, confirm_spend, estimate_replay, gather_limited, label, parse_model,
)
from backend.eval.scorers import _NUMBER_RE, _claims

JUDGE_TASKS = ("simulate_hiring_manager", "analyze_interview_performance")

# The letter is the last block of the simulator's prompt (below the cache break).
_LETTER_RE = re.compile(r'(Cover Letter:\n""")\n(.*)\n("""\s*)$', re.DOTALL)

GENERIC_OPENING = (
    "I am writing to apply for the position advertised on your website. I am a hard-working "
    "and motivated professional and I believe I would be a great fit for your company."
)


def split_letter(user: str) -> tuple[str, str, str] | None:
    m = _LETTER_RE.search(user)
    if not m:
        return None
    return user[: m.start(2)], m.group(2), user[m.end(2):]


def degrade(letter: str) -> dict[str, str]:
    """Named, mechanically worse versions of a letter. Each must score below the original."""
    paras = letter.split("\n\n")
    body = [i for i, p in enumerate(paras) if len(p.split()) >= 25]
    if not body:
        return {}
    out: dict[str, str] = {}

    evidence = max(body, key=lambda i: (len(_claims(paras[i])), len(paras[i])))
    out["drop_evidence"] = "\n\n".join(p for i, p in enumerate(paras) if i != evidence)

    generic = list(paras)
    generic[body[0]] = GENERIC_OPENING
    out["generic_opening"] = "\n\n".join(generic)

    out["truncated"] = "\n\n".join(paras[: max(1, body[len(body) // 2])])

    for i in body:
        m = _NUMBER_RE.search(paras[i])
        if m and m.group(0).isdigit():
            wrong = list(paras)
            wrong[i] = paras[i][: m.start()] + str(int(m.group(0)) * 3 + 1) + paras[i][m.end():]
            out["wrong_number"] = "\n\n".join(wrong)
            break
    return {k: v for k, v in out.items() if v.strip() and v != letter}


async def run_judge_check(
    set_name: str, models: list[str], samples: int = 5, assume_yes: bool = False
) -> int | None:
    s = await store.get_set(set_name)
    if not s:
        raise ValueError(f"No eval set named {set_name!r}")
    if s["task"] not in JUDGE_TASKS:
        raise ValueError(f"judge-check needs a set of {' or '.join(JUDGE_TASKS)}, not {s['task']}")
    if not 1 <= len(models) <= 2:
        raise ValueError("judge-check compares one or two models")
    cfgs = [parse_model(m) for m in models]
    cases = await store.load_cases(s["trace_ids"])

    variants: dict[int, dict[str, str]] = {}
    for case in cases:
        user = store.user_text(case["user_prompt"])
        found = [("original", user)]
        parts = split_letter(user) if s["task"] == "simulate_hiring_manager" else None
        if parts:
            head, letter, tail = parts
            found += [(name, head + text + tail) for name, text in degrade(letter).items()]
        variants[case["trace_id"]] = dict(found)

    n_variants = sum(len(v) for v in variants.values()) / max(1, len(cases))
    estimate = estimate_replay(cases, cfgs, samples) * n_variants
    if not confirm_spend(estimate, assume_yes, "this judge check"):
        return None

    run_id = await store.create_run(
        set_name=set_name, task=s["task"], kind="judge-check",
        baseline_model=label(cfgs[0]), candidate_model=label(cfgs[-1]), samples=samples,
    )
    jobs: list[Callable[[], Awaitable[None]]] = []
    for case in cases:
        for side, cfg in zip("AB", cfgs):
            for variant, user in variants[case["trace_id"]].items():
                for i in range(samples):
                    async def job(case=case, side=side, cfg=cfg, variant=variant, user=user, i=i) -> None:
                        out = await call_case(case, cfg, user=user)
                        await store.add_result(run_id, trace_id=case["trace_id"], side=side,
                                               sample=i, variant=variant, **out)
                    jobs.append(job)
    await gather_limited(jobs)
    return run_id
