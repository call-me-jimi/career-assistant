"""LLM judge calls: pairwise preference, briefing recall, fact recall.

The judge is one fixed model per run (settings.eval_judge_llm unless overridden)
and must not be either model under comparison — models favour their own writing.
"""

from __future__ import annotations

from typing import Literal

from backend.config import LLMConfig, load_settings
from backend.eval.replay import cost_usd, label, parse_model
from backend.eval.scorers import parse_json
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm

Winner = Literal["A", "B", "tie"]

# Not in KNOWN_TASKS on purpose: the judge's model comes from settings.eval_judge_llm
# or --judge, never from a per-task override, so the Settings page must not offer one.
JUDGE_TASK = "eval_judge"


class Judge:
    def __init__(self, spec: str | None = None) -> None:
        self.cfg: LLMConfig = parse_model(spec) if spec else load_settings().eval_judge_llm
        self.spent_usd = 0.0

    @property
    def name(self) -> str:
        return label(self.cfg)

    def check_independent(self, *models: str) -> None:
        for m in models:
            if m.split(":", 1)[-1] == self.cfg.model_name:
                raise ValueError(
                    f"Judge {self.name} is also a model under comparison ({m}); pick another with --judge"
                )

    async def _ask(self, stem: str, **ctx) -> dict | None:
        res = await call_llm(
            task=JUDGE_TASK, system=load_system_prompt(stem),
            user=render_user_prompt(stem, **ctx), llm=self.cfg,
        )
        self.spent_usd += cost_usd(self.cfg.model_name, res.input_tokens, res.output_tokens)
        return parse_json(res.text)

    async def _pick(self, task: str, request: str, first: str, second: str) -> str | None:
        out = await self._ask("eval_pairwise", task=task, request=request,
                              output_1=first, output_2=second)
        return str((out or {}).get("winner", "")).strip() or None

    async def pairwise(self, task: str, request: str, a: str, b: str) -> Winner:
        """Asked twice with the order swapped; a preference counts only if it survives
        the swap, which cancels the judge's position bias."""
        first = await self._pick(task, request, a, b)   # 1 = A
        second = await self._pick(task, request, b, a)  # 1 = B
        if first == "1" and second == "2":
            return "A"
        if first == "2" and second == "1":
            return "B"
        return "tie"

    async def _flags(self, stem: str, key: str, n: int, **ctx) -> list[bool] | None:
        out = await self._ask(stem, **ctx)
        flags = (out or {}).get(key)
        if not isinstance(flags, list) or len(flags) != n:
            return None
        return [bool(f) for f in flags]

    async def briefing_recall(self, briefing: str, questions: list[str]) -> list[bool] | None:
        return await self._flags("eval_briefing_recall", "anticipated", len(questions),
                                 briefing=briefing, questions=questions)

    async def fact_recall(self, text: str, facts: list[str]) -> list[bool] | None:
        return await self._flags("eval_fact_recall", "present", len(facts), text=text, facts=facts)
