"""LangGraph StateGraph wiring all nodes and edges.

The graph is compiled lazily with a checkpointer so the same graph can be
built against a fresh checkpointer per process.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agent.nodes.classify_flow import classify_flow_node
from backend.agent.nodes.cl_loop import cl_loop_node
from backend.agent.nodes.cl_review import cl_review_node
from backend.agent.nodes.collect_job import collect_job_node
from backend.agent.nodes.confirm_info import confirm_info_node
from backend.agent.nodes.cv_intake import cv_intake_node
from backend.agent.nodes.export_node import export_node, post_export_node
from backend.agent.nodes.extract_info import extract_info_node
from backend.agent.nodes.fill_missing_info import fill_missing_info_node
from backend.agent.nodes.greeting import greeting_node
from backend.agent.nodes.qa_nodes import qa_answer_node, qa_menu_node
from backend.agent.nodes.research_company import research_company_node
from backend.agent.nodes.strategy import strategy_node
from backend.agent.nodes.synthesize_learning import (
    review_learned_suggestion_node,
    synthesize_learning_node,
)
from backend.agent.state import ApplicationState


def build_graph(checkpointer):
    g = StateGraph(ApplicationState)

    g.add_node("greeting", greeting_node)
    g.add_node("cv_intake", cv_intake_node)
    g.add_node("collect_job", collect_job_node)
    g.add_node("extract_info", extract_info_node)
    g.add_node("fill_missing_info", fill_missing_info_node)
    g.add_node("confirm_info", confirm_info_node)
    g.add_node("research_company", research_company_node)
    g.add_node("classify_flow", classify_flow_node)
    g.add_node("strategy", strategy_node)
    g.add_node("cl_loop", cl_loop_node)
    g.add_node("cl_review", cl_review_node)
    g.add_node("qa_menu", qa_menu_node)
    g.add_node("qa_answer", qa_answer_node)
    g.add_node("export", export_node)
    g.add_node("post_export", post_export_node)
    g.add_node("synthesize_learning", synthesize_learning_node)
    g.add_node("review_learned_suggestion", review_learned_suggestion_node)

    g.add_edge(START, "greeting")
    g.add_edge("greeting", "cv_intake")
    g.add_edge("cv_intake", "collect_job")
    g.add_edge("collect_job", "extract_info")
    g.add_edge("extract_info", "fill_missing_info")
    g.add_edge("fill_missing_info", "confirm_info")
    g.add_edge("confirm_info", "research_company")
    g.add_edge("research_company", "classify_flow")
    g.add_edge("classify_flow", "strategy")
    g.add_edge("strategy", "cl_loop")
    g.add_edge("cl_loop", "cl_review")

    def cl_review_router(state: ApplicationState) -> str:
        return "cl_review" if state.phase == "cl_review" else "qa_menu"

    g.add_conditional_edges(
        "cl_review", cl_review_router, {"cl_review": "cl_review", "qa_menu": "qa_menu"}
    )

    # Q&A loop: qa_menu routes either to qa_answer (question pending) or export (done)
    def qa_menu_router(state: ApplicationState) -> str:
        return "qa_answer" if state.phase == "qa_answer" else "export"

    g.add_conditional_edges(
        "qa_menu", qa_menu_router, {"qa_answer": "qa_answer", "export": "export"}
    )
    g.add_edge("qa_answer", "qa_menu")

    g.add_edge("export", "post_export")

    def post_export_router(state: ApplicationState) -> str:
        return "qa_menu" if state.phase == "qa_menu" else "synthesize_learning"

    g.add_conditional_edges(
        "post_export",
        post_export_router,
        {"qa_menu": "qa_menu", "synthesize_learning": "synthesize_learning"},
    )

    g.add_edge("synthesize_learning", "review_learned_suggestion")
    g.add_edge("review_learned_suggestion", END)

    return g.compile(checkpointer=checkpointer)
