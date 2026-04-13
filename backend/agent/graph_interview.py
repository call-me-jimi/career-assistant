"""LangGraph StateGraph for the Interview Prep assistant.

Shares the profile + job intake prelude with the cover-letter graph, then
produces a single-pass interview briefing document.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agent.nodes.collect_job import collect_job_node
from backend.agent.nodes.confirm_info import confirm_info_node
from backend.agent.nodes.cv_intake import cv_intake_node
from backend.agent.nodes.export_node import export_node
from backend.agent.nodes.extract_info import extract_info_node
from backend.agent.nodes.fill_missing_info import fill_missing_info_node
from backend.agent.nodes.greeting import greeting_node
from backend.agent.nodes.interview_briefing import interview_briefing_node
from backend.agent.nodes.interview_context import interview_context_node
from backend.agent.nodes.research_company import research_company_node
from backend.agent.state import ApplicationState


def build_interview_graph(checkpointer):
    g = StateGraph(ApplicationState)

    g.add_node("greeting", greeting_node)
    g.add_node("cv_intake", cv_intake_node)
    g.add_node("collect_job", collect_job_node)
    g.add_node("extract_info", extract_info_node)
    g.add_node("fill_missing_info", fill_missing_info_node)
    g.add_node("confirm_info", confirm_info_node)
    g.add_node("research_company", research_company_node)
    g.add_node("interview_context", interview_context_node)
    g.add_node("interview_briefing", interview_briefing_node)
    g.add_node("export", export_node)

    g.add_edge(START, "greeting")
    g.add_edge("greeting", "cv_intake")
    g.add_edge("cv_intake", "collect_job")
    g.add_edge("collect_job", "extract_info")
    g.add_edge("extract_info", "fill_missing_info")
    g.add_edge("fill_missing_info", "confirm_info")
    g.add_edge("confirm_info", "research_company")
    g.add_edge("research_company", "interview_context")
    g.add_edge("interview_context", "interview_briefing")
    g.add_edge("interview_briefing", "export")
    g.add_edge("export", END)

    return g.compile(checkpointer=checkpointer)
