"""Replay traced prompts against another model and store the outputs side by side."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from backend.config import LLMConfig, load_settings
from backend.eval import store
from backend.llm.service import call_llm

STORED = "stored"
CONCURRENCY = 4


def parse_model(spec: str) -> LLMConfig:
    """"provider:model", or a bare model name whose provider is obvious from its prefix."""
    if ":" in spec:
        provider, model = spec.split(":", 1)
        return LLMConfig(provider=provider, model_name=model)
    if spec.startswith("claude-"):
        return LLMConfig(provider="anthropic", model_name=spec)
    if spec.startswith(("gpt-", "o1", "o3", "o4")):
        return LLMConfig(provider="openai", model_name=spec)
    raise ValueError(f"Cannot infer the provider of {spec!r}; write it as provider:model")


def label(cfg: LLMConfig) -> str:
    return f"{cfg.provider}:{cfg.model_name}"


def cost_usd(model: str | None, input_tokens: int, output_tokens: int, cache_read: int = 0,
             cache_write: int = 0) -> float:
    # Lazy import: routes pulls in the whole API module.
    from backend.api.routes import _cost_for

    return _cost_for(model, input_tokens, output_tokens, load_settings().model_pricing,
                     cache_read, cache_write)


def confirm_spend(estimate: float, assume_yes: bool, what: str) -> bool:
    cap = load_settings().eval_max_usd
    print(f"Estimated cost of {what}: ${estimate:.2f} (cap ${cap:.2f}; unpriced models count as $0)")
    if estimate <= cap or assume_yes:
        return True
    return input("Over the cap. Continue? [y/N] ").strip().lower() == "y"


def estimate_replay(cases: list[dict[str, Any]], models: list[LLMConfig], samples: int) -> float:
    return sum(
        cost_usd(m.model_name, c["input_tokens"] or 0, c["output_tokens"] or 0) * samples
        for c in cases
        for m in models
    )


async def call_case(case: dict[str, Any], cfg: LLMConfig, user: str | None = None) -> dict[str, Any]:
    """One call on a case's stored prompts (or a replacement user prompt). Never raises:
    a failed call becomes a result row with `error`, which the report counts."""
    started = time.monotonic()
    try:
        res = await call_llm(
            task=case["task"],
            system=case["system_prompt"] or None,
            user=user if user is not None else store.user_text(case["user_prompt"]),
            llm=cfg,
        )
    except Exception as exc:  # noqa: BLE001 — provider errors are data here
        return {"response_text": "", "error": f"{type(exc).__name__}: {exc}"[:500],
                "duration_ms": int((time.monotonic() - started) * 1000)}
    return {
        "response_text": res.text,
        "error": "truncated" if res.truncated else None,
        "input_tokens": res.input_tokens,
        "output_tokens": res.output_tokens,
        "cost_usd": cost_usd(cfg.model_name, res.input_tokens, res.output_tokens),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


async def gather_limited(jobs: list[Callable[[], Awaitable[None]]]) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0

    async def one(job: Callable[[], Awaitable[None]]) -> None:
        nonlocal done
        async with sem:
            await job()
        done += 1
        print(f"\r  {done}/{len(jobs)} calls", end="", flush=True)

    await asyncio.gather(*(one(j) for j in jobs))
    print()


def stored_result(case: dict[str, Any]) -> dict[str, Any]:
    """The traced output as the baseline — free, but a single sample."""
    return {
        "response_text": case["response_text"],
        "input_tokens": case["input_tokens"] or 0,
        "output_tokens": case["output_tokens"] or 0,
        "cost_usd": cost_usd(case["model"], case["input_tokens"] or 0, case["output_tokens"] or 0,
                             case["cache_read_tokens"] or 0, case["cache_write_tokens"] or 0),
        "duration_ms": case["duration_ms"] or 0,
    }


async def run_replay(
    set_name: str, candidate: str, baseline: str = STORED, samples: int = 3,
    assume_yes: bool = False,
) -> int | None:
    s = await store.get_set(set_name)
    if not s:
        raise ValueError(f"No eval set named {set_name!r}")
    cases = await store.load_cases(s["trace_ids"])
    cand = parse_model(candidate)
    base = None if baseline == STORED else parse_model(baseline)
    models = [cand] + ([base] if base else [])
    if not confirm_spend(estimate_replay(cases, models, samples), assume_yes, "this replay"):
        return None

    run_id = await store.create_run(
        set_name=set_name, task=s["task"], kind="replay",
        baseline_model=label(base) if base else STORED, candidate_model=label(cand), samples=samples,
    )
    jobs: list[Callable[[], Awaitable[None]]] = []
    for case in cases:
        if base is None:
            await store.add_result(run_id, trace_id=case["trace_id"], side="A", sample=0,
                                   **stored_result(case))
        for side, cfg in (("A", base), ("B", cand)):
            if cfg is None:
                continue
            for i in range(samples):
                async def job(case=case, side=side, cfg=cfg, i=i) -> None:
                    out = await call_case(case, cfg)
                    await store.add_result(run_id, trace_id=case["trace_id"], side=side, sample=i, **out)
                jobs.append(job)
    await gather_limited(jobs)
    return run_id
