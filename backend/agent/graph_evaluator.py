"""LangGraph for the Interview Evaluator assistant.

Shared intake (CV, job, profile, confirm) → evaluator_context → audio
upload → local transcription → structured analysis → review loop → export.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agent.nodes.collect_job import collect_job_node
from backend.agent.nodes.confirm_info import confirm_info_node
from backend.agent.nodes.cv_intake import cv_intake_node
from backend.agent.nodes.evaluator import (
    evaluator_analyze_node,
    evaluator_context_node,
    evaluator_review_node,
    evaluator_transcribe_node,
    evaluator_upload_node,
)
from backend.agent.nodes.export_node import export_node, post_export_node
from backend.agent.nodes.extract_info import extract_info_node
from backend.agent.nodes.fill_missing_info import fill_missing_info_node
from backend.agent.nodes.language_switch import language_switch_node
from backend.agent.nodes.greeting import greeting_node
from backend.agent.nodes.select_journey import select_journey_node
from backend.agent.state import ApplicationState


def build_evaluator_graph(checkpointer):
    g = StateGraph(ApplicationState)

    g.add_node("greeting", greeting_node)
    g.add_node("cv_intake", cv_intake_node)
    g.add_node("select_journey", select_journey_node)
    g.add_node("collect_job", collect_job_node)
    g.add_node("extract_info", extract_info_node)
    g.add_node("language_switch", language_switch_node)
    g.add_node("fill_missing_info", fill_missing_info_node)
    g.add_node("confirm_info", confirm_info_node)
    g.add_node("evaluator_context", evaluator_context_node)
    g.add_node("evaluator_upload", evaluator_upload_node)
    g.add_node("evaluator_transcribe", evaluator_transcribe_node)
    g.add_node("evaluator_analyze", evaluator_analyze_node)
    g.add_node("evaluator_review", evaluator_review_node)
    g.add_node("export", export_node)
    g.add_node("post_export", post_export_node)

    g.add_edge(START, "greeting")
    g.add_edge("greeting", "cv_intake")
    g.add_edge("cv_intake", "select_journey")

    def select_journey_router(state: ApplicationState) -> str:
        targets = {"select_journey", "collect_job", "evaluator_context"}
        return state.phase if state.phase in targets else "collect_job"

    g.add_conditional_edges(
        "select_journey",
        select_journey_router,
        {t: t for t in ("select_journey", "collect_job", "evaluator_context")},
    )
    g.add_edge("collect_job", "extract_info")
    g.add_edge("extract_info", "language_switch")
    g.add_edge("language_switch", "fill_missing_info")
    g.add_edge("fill_missing_info", "confirm_info")
    g.add_edge("confirm_info", "evaluator_context")
    g.add_edge("evaluator_context", "evaluator_upload")

    def upload_router(state: ApplicationState) -> str:
        return (
            "evaluator_transcribe"
            if state.phase == "evaluator_transcribe"
            else "evaluator_upload"
        )

    g.add_conditional_edges(
        "evaluator_upload",
        upload_router,
        {
            "evaluator_transcribe": "evaluator_transcribe",
            "evaluator_upload": "evaluator_upload",
        },
    )

    def transcribe_router(state: ApplicationState) -> str:
        return (
            "evaluator_analyze"
            if state.phase == "evaluator_analyze"
            else "evaluator_upload"
        )

    g.add_conditional_edges(
        "evaluator_transcribe",
        transcribe_router,
        {
            "evaluator_analyze": "evaluator_analyze",
            "evaluator_upload": "evaluator_upload",
        },
    )

    g.add_edge("evaluator_analyze", "evaluator_review")

    def review_router(state: ApplicationState) -> str:
        return "evaluator_review" if state.phase == "evaluator_review" else "export"

    g.add_conditional_edges(
        "evaluator_review",
        review_router,
        {"evaluator_review": "evaluator_review", "export": "export"},
    )

    g.add_edge("export", "post_export")

    def post_export_router(state: ApplicationState) -> str:
        return END

    g.add_conditional_edges("post_export", post_export_router, {END: END})

    return g.compile(checkpointer=checkpointer)
