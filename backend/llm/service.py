"""Multi-provider LLM service built on LangChain chat models.

Using LangChain chat models lets OpenInference auto-instrument every call
so the observability pipeline sees inputs, outputs, tokens, and latency
without any manual plumbing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from backend.config import LLMConfig, get_api_key, get_ollama_base_url, load_settings
from backend.llm.schemas import HiringManagerFeedback

log = logging.getLogger("assistant.llm")


@dataclass
class LLMCallResult:
    text: str
    model: str
    provider: str


def _resolve_config(task: str | None) -> LLMConfig:
    settings = load_settings()
    if task and task in settings.task_llm_configs:
        cfg = settings.task_llm_configs[task]
        return LLMConfig(
            provider=cfg.provider or settings.default_llm.provider,
            model_name=cfg.model_name or settings.default_llm.model_name,
            base_url=cfg.base_url or settings.default_llm.base_url,
        )
    return settings.default_llm


def build_chat_model(task: str | None = None):
    cfg = _resolve_config(task)
    provider = cfg.provider.lower()
    api_key = get_api_key(provider)
    if provider in {"anthropic", "openai"} and not api_key:
        raise RuntimeError(
            f"Missing API key for provider '{provider}'. "
            f"Set {provider.upper()}_API_KEY (or LLM_API_KEY) in assistant/.env."
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs_anthropic: dict[str, Any] = {
            "model": cfg.model_name,
            "api_key": api_key,
            "max_tokens": 8192,
        }
        if not cfg.model_name.lower().startswith("claude-opus-4"):
            kwargs_anthropic["temperature"] = 0.7
        return ChatAnthropic(**kwargs_anthropic), cfg
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": cfg.model_name, "api_key": api_key}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        # Some reasoning models reject temperature overrides; default otherwise.
        if not cfg.model_name.lower().startswith(("gpt-5", "o1", "o3")):
            kwargs["temperature"] = 0.7
        return ChatOpenAI(**kwargs), cfg
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=cfg.model_name,
            base_url=cfg.base_url or get_ollama_base_url(),
            temperature=0.7,
        ), cfg

    raise ValueError(f"Unsupported provider: {cfg.provider}")


def _messages(system: str | None, user: str, history: list[dict] | None = None):
    msgs: list = []
    if system:
        msgs.append(SystemMessage(content=system))
    for h in history or []:
        role = h.get("role")
        content = h.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
        elif role == "system":
            msgs.append(SystemMessage(content=content))
    msgs.append(HumanMessage(content=user))
    return msgs


async def call_llm(
    *,
    task: str,
    system: str | None,
    user: str,
    session_id: str | None = None,
    history: list[dict] | None = None,
) -> LLMCallResult:
    """Single-turn LLM call tagged with task + session metadata.

    The tags and metadata are picked up by OpenInference/LangChain callbacks
    so the custom OTel span processor can attribute spans to the right session.
    """
    from backend.observability.callbacks import event_bus_callback

    chat, cfg = build_chat_model(task)
    messages = _messages(system, user, history)
    config: RunnableConfig = {
        "tags": [f"task:{task}"] + ([f"session:{session_id}"] if session_id else []),
        "metadata": {
            "task": task,
            "session_id": session_id,
            "provider": cfg.provider,
            "model": cfg.model_name,
        },
        "run_name": task,
        "callbacks": [event_bus_callback],
    }
    log.info("llm call task=%s provider=%s model=%s", task, cfg.provider, cfg.model_name)
    ai: AIMessage = await chat.ainvoke(messages, config=config)
    text = ai.content if isinstance(ai.content, str) else str(ai.content)
    return LLMCallResult(text=text, model=cfg.model_name, provider=cfg.provider)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict:
    """Best-effort JSON extraction from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        # strip code fence
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK_RE.search(text)
        if m:
            return json.loads(m.group(0))
        raise


def parse_hm_feedback(text: str) -> HiringManagerFeedback:
    data = extract_json(text)
    return HiringManagerFeedback.model_validate(data)
