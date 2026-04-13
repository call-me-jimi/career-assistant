"""LangGraph StateGraph for the Career Advisor assistant.

Loop: greeting → cv_intake → advisor_chat ⇄ swot_summary → export.

No job intake — this assistant is about the candidate's career, not a
specific role.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agent.nodes.advisor_chat import advisor_chat_node
from backend.agent.nodes.cv_intake import cv_intake_node
from backend.agent.nodes.export_node import export_node
from backend.agent.nodes.greeting import greeting_node
from backend.agent.nodes.swot_summary import swot_summary_node
from backend.agent.state import ApplicationState


def build_advisor_graph(checkpointer):
    g = StateGraph(ApplicationState)

    g.add_node("greeting", greeting_node)
    g.add_node("cv_intake", cv_intake_node)
    g.add_node("advisor_chat", advisor_chat_node)
    g.add_node("advisor_swot", swot_summary_node)
    g.add_node("export", export_node)

    g.add_edge(START, "greeting")
    g.add_edge("greeting", "cv_intake")
    g.add_edge("cv_intake", "advisor_chat")

    def advisor_router(state: ApplicationState) -> str:
        if state.phase == "advisor_swot":
            return "advisor_swot"
        if state.phase == "export":
            return "export"
        return "advisor_chat"

    g.add_conditional_edges(
        "advisor_chat",
        advisor_router,
        {"advisor_chat": "advisor_chat", "advisor_swot": "advisor_swot", "export": "export"},
    )
    g.add_edge("advisor_swot", "advisor_chat")
    g.add_edge("export", END)

    return g.compile(checkpointer=checkpointer)
