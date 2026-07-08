"""LangChain callback handler that bridges LLM runs to the event bus.

We use LangChain's callback API (rather than OTel spans directly) as the
primary source for in-app LLM cards because it gives us reliable access
to model, tokens, timing, and per-call metadata (session_id, task) without
span-attribute parsing.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from uuid import UUID

from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from backend.observability.event_bus import bus
from backend.storage.traces import record_trace


def _split_messages(messages: list[list[BaseMessage]]) -> tuple[str, str]:
    """Split a flattened message batch into (system_prompt, user_prompt).

    Anything tagged 'system' goes into system_prompt; everything else
    (human/ai/tool) goes into user_prompt with role labels so multi-turn
    history remains legible.
    """
    system_parts: list[str] = []
    user_parts: list[str] = []
    for batch in messages:
        for m in batch:
            content = m.content if isinstance(m.content, str) else str(m.content)
            if m.type == "system":
                system_parts.append(content)
            else:
                user_parts.append(f"[{m.type}] {content}")
    return "\n\n".join(system_parts), "\n\n".join(user_parts)


class EventBusCallbackHandler(AsyncCallbackHandler):
    """Emits llm.start / llm.end events to the event bus per LangChain run.

    Metadata flows from `call_llm` (service.py) via the RunnableConfig:
      metadata = {"task": ..., "session_id": ..., "provider": ..., "model": ...}
    """

    def __init__(self) -> None:
        self._starts: dict[UUID, dict[str, Any]] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        system_prompt, user_prompt = _split_messages(messages)
        await self._on_start(
            run_id=run_id,
            metadata=metadata or {},
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        await self._on_start(
            run_id=run_id,
            metadata=metadata or {},
            system_prompt="",
            user_prompt="\n\n".join(prompts),
        )

    async def _on_start(
        self,
        *,
        run_id: UUID,
        metadata: dict[str, Any],
        system_prompt: str,
        user_prompt: str,
    ) -> None:
        session_id = metadata.get("session_id")
        card_id = str(uuid.uuid4())
        started_at = time.time()
        self._starts[run_id] = {
            "card_id": card_id,
            "started_at": started_at,
            "session_id": session_id,
            "task": metadata.get("task"),
            "provider": metadata.get("provider"),
            "model": metadata.get("model"),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
        if not session_id:
            return
        bus.publish(
            session_id,
            {
                "type": "llm.start",
                "card_id": card_id,
                "timestamp": started_at,
                "task": metadata.get("task"),
                "provider": metadata.get("provider"),
                "model": metadata.get("model"),
            },
        )

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        started = self._starts.pop(run_id, None)
        if not started:
            return
        ended_at = time.time()
        duration_ms = int((ended_at - started["started_at"]) * 1000)
        input_tokens, output_tokens = _usage_from_result(response)
        output_text = _response_text(response)
        session_id = started["session_id"]
        if session_id:
            bus.publish(
                session_id,
                {
                    "type": "llm.end",
                    "card_id": started["card_id"],
                    "timestamp": ended_at,
                    "duration_ms": duration_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "task": started["task"],
                    "provider": started["provider"],
                    "model": started["model"],
                },
            )
            try:
                await record_trace(
                    session_id=session_id,
                    card_id=started["card_id"],
                    task=started["task"],
                    provider=started["provider"],
                    model=started["model"],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=duration_ms,
                    system_prompt=started["system_prompt"],
                    user_prompt=started["user_prompt"],
                    response_text=output_text,
                )
            except Exception:  # pragma: no cover — trace persistence must not break calls
                pass

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._starts.pop(run_id, None)
        if not started:
            return
        session_id = started["session_id"]
        if not session_id:
            return
        bus.publish(
            session_id,
            {
                "type": "llm.error",
                "card_id": started["card_id"],
                "timestamp": time.time(),
                "error": str(error),
                "task": started["task"],
                "provider": started["provider"],
                "model": started["model"],
            },
        )


def _usage_from_result(response: LLMResult) -> tuple[int, int]:
    usage = (response.llm_output or {}).get("token_usage") or (response.llm_output or {}).get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    if input_tokens or output_tokens:
        return input_tokens, output_tokens
    # Fallback: look into generation message usage_metadata (Anthropic/OpenAI LangChain >=0.3)
    for gen_list in response.generations:
        for gen in gen_list:
            msg = getattr(gen, "message", None)
            meta = getattr(msg, "usage_metadata", None) if msg else None
            if meta:
                return int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0))
    return 0, 0


def _response_text(response: LLMResult) -> str:
    parts: list[str] = []
    for gen_list in response.generations:
        for gen in gen_list:
            parts.append(gen.text or "")
    return "\n".join(parts)


event_bus_callback = EventBusCallbackHandler()
