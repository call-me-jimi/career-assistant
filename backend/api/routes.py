"""REST routes: session lifecycle, profile listing, trace detail."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.agent.interrupts import emit_message
from backend.agent.runner import registry
from backend.config import KNOWN_TASKS, LLMConfig, ModelPricing, load_settings, save_settings
from backend.storage.playbook import get_playbook, remove_playbook_item, upsert_playbook
from backend.storage.profiles import delete_profile, get_profile, list_profiles
from backend.storage.sessions import ASSISTANT_TYPES, create_session, get_session
from backend.storage.stats import get_global_stats
from backend.storage.suggestions import (
    approve_suggestion,
    count_pending,
    list_pending,
    reject_suggestion,
)
from backend.storage.traces import get_trace, list_traces

router = APIRouter(prefix="/api")


def _cost_for(model: str | None, input_tokens: int, output_tokens: int, pricing: dict[str, ModelPricing]) -> float:
    if not model or model not in pricing:
        return 0.0
    p = pricing[model]
    return (input_tokens / 1_000_000.0) * p.input_per_mtok + (output_tokens / 1_000_000.0) * p.output_per_mtok


class StartSessionPayload(BaseModel):
    assistant_type: str = "cover_letter"
    language: str = "English"


@router.post("/sessions")
async def start_session(payload: StartSessionPayload | None = None) -> dict:
    assistant_type = (payload.assistant_type if payload else "cover_letter") or "cover_letter"
    language = (payload.language if payload else "English") or "English"
    if assistant_type not in ASSISTANT_TYPES:
        raise HTTPException(400, f"unknown assistant_type: {assistant_type}")
    session_id = await create_session(assistant_type, language)
    registry.get_or_start(session_id)
    return {"session_id": session_id, "assistant_type": assistant_type, "language": language}


@router.get("/sessions/{session_id}")
async def session_info(session_id: str) -> dict:
    info = await get_session(session_id)
    if not info:
        raise HTTPException(404, "session not found")
    return info


@router.get("/profiles")
async def profiles() -> dict:
    rows = await list_profiles()
    for r in rows:
        r["pending_suggestion_count"] = await count_pending(r["profile_id"])
    return {"profiles": rows}


@router.get("/profiles/{profile_id}")
async def profile_detail(profile_id: str) -> dict:
    p = await get_profile(profile_id)
    if not p:
        raise HTTPException(404, "profile not found")
    return p


@router.delete("/profiles/{profile_id}")
async def remove_profile(profile_id: str) -> dict:
    deleted = await delete_profile(profile_id)
    if not deleted:
        raise HTTPException(404, "profile not found")
    return {"ok": True}


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
    google_sheets_spreadsheet_id: str = ""


EDITABLE_FIELDS = {
    "language",
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
    _FIELD_LABELS = {
        "applicant_name": "name", "cv_text": "CV", "candidate_profile": "candidate profile",
        "job_url": "job URL", "job_raw_text": "job ad", "job_title": "job title",
        "company_name": "company", "job_description": "job description",
        "company_description": "company description", "location": "location",
        "job_source_type": "job source", "alignment_strategy": "alignment strategy",
        "inferred_role_context": "role context", "positioning_strategy": "positioning strategy",
        "cover_letter": "cover letter", "language": "language",
        "interview_context": "interview context", "interview_briefing": "interview briefing",
        "advisor_swot": "SWOT analysis",
    }
    labels = [_FIELD_LABELS.get(k, k.replace("_", " ")) for k in clean]
    emit_message(session_id, f"I updated the {', '.join(labels)}.", role="user")
    return {"ok": True, "updated": list(clean.keys())}


@router.get("/sessions/{session_id}/exports/{kind}")
async def download_export(session_id: str, kind: str):
    """Stream a previously generated export file back to the user.

    Looks up the matching ExportResult on the running session's state. Prefers
    paths in the temp `career_assistant_exports` tree (those were written
    specifically for download) over folder-dump paths.
    """
    runner = registry.get(session_id)
    if not runner:
        raise HTTPException(404, "session not active")
    values = await runner.get_state_values()
    if values is None:
        raise HTTPException(409, "session state not ready yet")

    raw_results = values.get("export_results") or []
    matches: list[str] = []
    for r in raw_results:
        r_kind = r.kind if hasattr(r, "kind") else r.get("kind")
        r_path = r.path if hasattr(r, "path") else r.get("path")
        if r_kind == kind and r_path:
            matches.append(r_path)

    if not matches:
        raise HTTPException(404, f"no {kind} export available")

    if kind == "sheets":
        return {"url": matches[-1]}

    # Prefer the temp-dir copy (written for download) if both exist.
    chosen = next(
        (p for p in reversed(matches) if "career_assistant_exports" in p),
        matches[-1],
    )
    p = Path(chosen)
    if not p.exists():
        raise HTTPException(410, "export file no longer on disk")
    return FileResponse(str(p), filename=p.name)


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


@router.get("/stats")
async def global_stats() -> dict:
    settings = load_settings()
    pricing = settings.model_pricing
    raw = await get_global_stats()

    sessions_by_type: dict[str, int] = raw["sessions_by_type"]
    trace_rows: list[tuple] = raw["trace_rows"]

    by_type: dict[str, dict] = {}
    for assistant_type, model, calls, input_tokens, output_tokens in trace_rows:
        entry = by_type.setdefault(
            assistant_type, {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        entry["llm_calls"] += calls
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["cost_usd"] += _cost_for(model, input_tokens, output_tokens, pricing)

    total_sessions = sum(sessions_by_type.values())
    total_calls = sum(e["llm_calls"] for e in by_type.values())
    total_in = sum(e["input_tokens"] for e in by_type.values())
    total_out = sum(e["output_tokens"] for e in by_type.values())
    total_cost = sum(e["cost_usd"] for e in by_type.values())

    return {
        "sessions_by_type": sessions_by_type,
        "totals": {
            "sessions": total_sessions,
            "llm_calls": total_calls,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cost_usd": total_cost,
        },
        "by_assistant_type": by_type,
    }


@router.get("/settings")
async def get_settings() -> dict:
    s = load_settings()
    return {
        "default_llm": s.default_llm.model_dump(),
        "task_llm_configs": {k: v.model_dump() for k, v in s.task_llm_configs.items()},
        "model_pricing": {k: v.model_dump() for k, v in s.model_pricing.items()},
        "known_tasks": KNOWN_TASKS,
        "google_sheets_spreadsheet_id": s.google_sheets_spreadsheet_id,
    }


@router.put("/settings")
async def update_settings(payload: SettingsPayload) -> dict:
    s = load_settings()
    s.default_llm = payload.default_llm
    s.task_llm_configs = {
        k: v for k, v in payload.task_llm_configs.items() if v.provider and v.model_name
    }
    s.model_pricing = {k: v for k, v in payload.model_pricing.items() if k.strip()}
    s.google_sheets_spreadsheet_id = payload.google_sheets_spreadsheet_id
    save_settings(s)
    return {"ok": True}


@router.get("/profiles/{profile_id}/playbook")
async def profile_playbook(profile_id: str) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    return await get_playbook(profile_id)


@router.patch("/profiles/{profile_id}/playbook")
async def patch_playbook(profile_id: str, payload: dict) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    await upsert_playbook(profile_id, payload)
    return {"ok": True}


@router.delete("/profiles/{profile_id}/playbook/{category}/{index}")
async def delete_playbook_item(profile_id: str, category: str, index: int) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    removed = await remove_playbook_item(profile_id, category, index)
    if not removed:
        raise HTTPException(404, "playbook item not found")
    return {"ok": True}


@router.get("/profiles/{profile_id}/suggestions")
async def profile_suggestions(profile_id: str) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    return {
        "suggestions": await list_pending(profile_id),
        "pending_count": await count_pending(profile_id),
    }


@router.post("/profiles/{profile_id}/suggestions/{suggestion_id}/approve")
async def approve_profile_suggestion(profile_id: str, suggestion_id: int) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    result = await approve_suggestion(suggestion_id)
    if not result:
        raise HTTPException(404, "suggestion not found or not pending")
    if result["profile_id"] != profile_id:
        raise HTTPException(404, "suggestion not found for this profile")
    return {"ok": True, "suggestion": result}


@router.post("/profiles/{profile_id}/suggestions/{suggestion_id}/reject")
async def reject_profile_suggestion(profile_id: str, suggestion_id: int) -> dict:
    if not await get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    ok = await reject_suggestion(suggestion_id)
    if not ok:
        raise HTTPException(404, "suggestion not found or not pending")
    return {"ok": True}
