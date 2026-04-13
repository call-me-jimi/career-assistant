"""REST routes: session lifecycle, profile listing, trace detail."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.agent.runner import registry
from backend.config import KNOWN_TASKS, LLMConfig, ModelPricing, load_settings, save_settings
from backend.storage.profiles import list_profiles
from backend.storage.sessions import ASSISTANT_TYPES, create_session, get_session
from backend.storage.traces import get_trace, list_traces

router = APIRouter(prefix="/api")


def _cost_for(model: str | None, input_tokens: int, output_tokens: int, pricing: dict[str, ModelPricing]) -> float:
    if not model or model not in pricing:
        return 0.0
    p = pricing[model]
    return (input_tokens / 1_000_000.0) * p.input_per_mtok + (output_tokens / 1_000_000.0) * p.output_per_mtok


class StartSessionPayload(BaseModel):
    assistant_type: str = "cover_letter"


@router.post("/sessions")
async def start_session(payload: StartSessionPayload | None = None) -> dict:
    assistant_type = (payload.assistant_type if payload else "cover_letter") or "cover_letter"
    if assistant_type not in ASSISTANT_TYPES:
        raise HTTPException(400, f"unknown assistant_type: {assistant_type}")
    session_id = await create_session(assistant_type)
    registry.get_or_start(session_id)
    return {"session_id": session_id, "assistant_type": assistant_type}


@router.get("/sessions/{session_id}")
async def session_info(session_id: str) -> dict:
    info = await get_session(session_id)
    if not info:
        raise HTTPException(404, "session not found")
    return info


@router.get("/profiles")
async def profiles() -> dict:
    return {"profiles": await list_profiles()}


@router.get("/sessions/{session_id}/traces")
async def session_traces(session_id: str) -> dict:
    settings = load_settings()
    pricing = settings.model_pricing
    traces = await list_traces(session_id)
    enriched: list[dict] = []
    for t in traces:
        cost = _cost_for(t.get("model"), t["input_tokens"], t["output_tokens"], pricing)
        enriched.append({**t, "cost_usd": cost})
    return {"traces": enriched}


@router.get("/sessions/{session_id}/traces/{card_id}")
async def trace_detail(session_id: str, card_id: str) -> dict:
    trace = await get_trace(session_id, card_id)
    if not trace:
        raise HTTPException(404, "trace not found")
    settings = load_settings()
    trace["cost_usd"] = _cost_for(
        trace.get("model"), trace["input_tokens"], trace["output_tokens"], settings.model_pricing
    )
    return trace


@router.get("/graph/mermaid")
async def graph_mermaid(assistant_type: str = "cover_letter") -> dict:
    """Return the static LangGraph topology as a Mermaid source string."""
    from backend.agent.runner import GRAPH_BUILDERS

    builder = GRAPH_BUILDERS.get(assistant_type)
    if builder is None:
        raise HTTPException(400, f"unknown assistant_type: {assistant_type}")
    compiled = builder(checkpointer=None)
    mermaid = compiled.get_graph().draw_mermaid()
    return {"mermaid": mermaid}


class SettingsPayload(BaseModel):
    default_llm: LLMConfig
    task_llm_configs: dict[str, LLMConfig]
    model_pricing: dict[str, ModelPricing] = {}


EDITABLE_FIELDS = {
    "applicant_name",
    "cv_text",
    "candidate_profile",
    "job_url",
    "job_raw_text",
    "job_title",
    "company_name",
    "job_description",
    "company_description",
    "location",
    "job_source_type",
    "alignment_strategy",
    "inferred_role_context",
    "positioning_strategy",
    "cover_letter",
    "interview_context",
    "interview_briefing",
    "advisor_swot",
}


@router.get("/sessions/{session_id}/state")
async def get_session_state(session_id: str) -> dict:
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    values = await runner.get_state_values()
    if values is None:
        raise HTTPException(409, "session state not ready yet")
    editable = {k: values.get(k, "") for k in EDITABLE_FIELDS}
    versions_raw = values.get("cover_letter_versions") or []
    versions = [
        v.model_dump() if hasattr(v, "model_dump") else v
        for v in versions_raw
    ]
    return {
        "session_id": session_id,
        "phase": values.get("phase", ""),
        "paused": runner._paused,
        "fields": editable,
        "cover_letter_versions": versions,
        "best_version_id": values.get("best_version_id") or None,
    }


@router.patch("/sessions/{session_id}/state")
async def patch_session_state(session_id: str, patch: dict) -> dict:
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    clean = {k: v for k, v in patch.items() if k in EDITABLE_FIELDS}
    if not clean:
        raise HTTPException(400, "no editable fields in patch")
    ok = await runner.update_state_values(clean)
    if not ok:
        raise HTTPException(
            409,
            "session is currently running — wait until the assistant is waiting for your input, then retry.",
        )
    return {"ok": True, "updated": list(clean.keys())}


@router.post("/sessions/{session_id}/select-version")
async def select_cover_letter_version(session_id: str, body: dict) -> dict:
    version_id = body.get("version_id")
    if not version_id:
        raise HTTPException(400, "version_id required")
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    values = await runner.get_state_values()
    if values is None:
        raise HTTPException(409, "session state not ready yet")
    versions_raw = values.get("cover_letter_versions") or []
    matched = None
    for v in versions_raw:
        vid = v.version_id if hasattr(v, "version_id") else v.get("version_id")
        text = v.text if hasattr(v, "text") else v.get("text", "")
        if vid == version_id:
            matched = text
            break
    if matched is None:
        raise HTTPException(404, "version not found")
    ok = await runner.update_state_values({
        "best_version_id": version_id,
        "cover_letter": matched,
    })
    if not ok:
        raise HTTPException(409, "session is running — wait until paused")
    return {"ok": True, "best_version_id": version_id}


@router.get("/settings")
async def get_settings() -> dict:
    s = load_settings()
    return {
        "default_llm": s.default_llm.model_dump(),
        "task_llm_configs": {k: v.model_dump() for k, v in s.task_llm_configs.items()},
        "model_pricing": {k: v.model_dump() for k, v in s.model_pricing.items()},
        "known_tasks": KNOWN_TASKS,
    }


@router.put("/settings")
async def update_settings(payload: SettingsPayload) -> dict:
    s = load_settings()
    s.default_llm = payload.default_llm
    s.task_llm_configs = {
        k: v for k, v in payload.task_llm_configs.items() if v.provider and v.model_name
    }
    s.model_pricing = {k: v for k, v in payload.model_pricing.items() if k.strip()}
    save_settings(s)
    return {"ok": True}
