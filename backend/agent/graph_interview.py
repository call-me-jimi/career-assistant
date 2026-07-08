"""LangGraph StateGraph for the Interview Prep assistant.

Shares the profile + job intake prelude with the cover-letter graph, then
produces an interview briefing with a revision loop, a coach menu offering
mock interview / practice / tech deep-dive / questions-to-ask, and finally
export.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agent.nodes.collect_job import collect_job_node
from backend.agent.nodes.confirm_info import confirm_info_node
from backend.agent.nodes.cv_intake import cv_intake_node
from backend.agent.nodes.export_node import export_node, post_export_node
from backend.agent.nodes.extract_info import extract_info_node
from backend.agent.nodes.fill_missing_info import fill_missing_info_node
from backend.agent.nodes.language_switch import language_switch_node
from backend.agent.nodes.greeting import greeting_node
from backend.agent.nodes.load_coaching_history import load_coaching_history_node
from backend.agent.nodes.interview_briefing import interview_briefing_node
from backend.agent.nodes.interview_context import interview_context_node
from backend.agent.nodes.interview_extras import (
    interview_menu_node,
    interview_practice_node,
    interview_questions_node,
    interview_tech_node,
    mock_interview_answer_node,
    mock_interview_node,
)
from backend.agent.nodes.interview_review import interview_review_node
from backend.agent.nodes.research_company import research_company_node
from backend.agent.state import ApplicationState


def build_interview_graph(checkpointer):
    g = StateGraph(ApplicationState)

    g.add_node("greeting", greeting_node)
    g.add_node("load_coaching_history", load_coaching_history_node)
    g.add_node("cv_intake", cv_intake_node)
    g.add_node("collect_job", collect_job_node)
    g.add_node("extract_info", extract_info_node)
    g.add_node("language_switch", language_switch_node)
    g.add_node("fill_missing_info", fill_missing_info_node)
    g.add_node("confirm_info", confirm_info_node)
    g.add_node("research_company", research_company_node)
    g.add_node("interview_context", interview_context_node)
    g.add_node("interview_briefing", interview_briefing_node)
    g.add_node("interview_review", interview_review_node)
    g.add_node("interview_menu", interview_menu_node)
    g.add_node("interview_mock", mock_interview_node)
    g.add_node("interview_mock_answer", mock_interview_answer_node)
    g.add_node("interview_practice", interview_practice_node)
    g.add_node("interview_tech", interview_tech_node)
    g.add_node("interview_questions", interview_questions_node)
    g.add_node("export", export_node)
    g.add_node("post_export", post_export_node)

    g.add_edge(START, "greeting")
    g.add_edge("greeting", "load_coaching_history")
    g.add_edge("load_coaching_history", "cv_intake")
    g.add_edge("cv_intake", "collect_job")
    g.add_edge("collect_job", "extract_info")
    g.add_edge("extract_info", "language_switch")
    g.add_edge("language_switch", "fill_missing_info")
    g.add_edge("fill_missing_info", "confirm_info")
    g.add_edge("confirm_info", "research_company")
    g.add_edge("research_company", "interview_context")
    g.add_edge("interview_context", "interview_briefing")
    g.add_edge("interview_briefing", "interview_review")

    def review_router(state: ApplicationState) -> str:
        return "interview_review" if state.phase == "interview_review" else "interview_menu"

    g.add_conditional_edges(
        "interview_review",
        review_router,
        {"interview_review": "interview_review", "interview_menu": "interview_menu"},
    )

    def menu_router(state: ApplicationState) -> str:
        target = {
            "interview_mock": "interview_mock",
            "interview_practice": "interview_practice",
            "interview_tech": "interview_tech",
            "interview_questions": "interview_questions",
        }.get(state.phase)
        return target or "export"

    g.add_conditional_edges(
        "interview_menu",
        menu_router,
        {
            "interview_mock": "interview_mock",
            "interview_practice": "interview_practice",
            "interview_tech": "interview_tech",
            "interview_questions": "interview_questions",
            "export": "export",
        },
    )

    g.add_edge("interview_mock", "interview_mock_answer")

    def mock_answer_router(state: ApplicationState) -> str:
        return "interview_mock" if state.phase == "interview_mock" else "interview_menu"

    g.add_conditional_edges(
        "interview_mock_answer",
        mock_answer_router,
        {"interview_mock": "interview_mock", "interview_menu": "interview_menu"},
    )

    g.add_edge("interview_practice", "interview_menu")
    g.add_edge("interview_tech", "interview_menu")
    g.add_edge("interview_questions", "interview_menu")
    g.add_edge("export", "post_export")

    def post_export_router(state: ApplicationState) -> str:
        return "interview_menu" if state.phase == "interview_menu" else END

    g.add_conditional_edges(
        "post_export",
        post_export_router,
        {"interview_menu": "interview_menu", END: END},
    )

    return g.compile(checkpointer=checkpointer)
