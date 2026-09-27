"""Assembles the LangGraph state machine."""

from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings
from app.db.catalog import SchemaCatalog
from app.graph.nodes import AgentNodes
from app.graph.state import AgentState
from app.llm import LLM


def build_graph(
    llm: LLM,
    catalog: SchemaCatalog,
    db_path: Path,
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    n = AgentNodes(llm, catalog, db_path, settings)
    g = StateGraph(AgentState)

    for name in (
        "input_guard", "classify_intent", "reject", "clarify", "retrieve_schema", "answer_schema",
        "check_user_sql", "generate_sql", "run_data_tools", "validate_sql", "cannot_answer",
        "generation_failed", "optimize_sql", "explain", "respond",
    ):
        g.add_node(name, getattr(n, name))

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", n.route_after_guard, ["classify_intent", "respond"])
    g.add_conditional_edges(
        "classify_intent", n.route_after_classify, ["reject", "clarify", "retrieve_schema"]
    )
    g.add_conditional_edges(
        "retrieve_schema", n.route_after_schema, ["answer_schema", "check_user_sql", "generate_sql"]
    )
    g.add_conditional_edges("check_user_sql", n.route_after_check, ["reject", "optimize_sql", "generate_sql"])
    g.add_conditional_edges(
        "generate_sql",
        n.route_after_generate,
        ["generate_sql", "run_data_tools", "validate_sql", "cannot_answer", "generation_failed"],
    )
    g.add_edge("run_data_tools", "generate_sql")
    g.add_conditional_edges(
        "validate_sql", n.route_after_validate, ["optimize_sql", "generate_sql", "generation_failed"]
    )
    g.add_edge("optimize_sql", "explain")
    g.add_edge("explain", "respond")
    for terminal in ("reject", "clarify", "answer_schema", "cannot_answer", "generation_failed"):
        g.add_edge(terminal, "respond")
    g.add_edge("respond", END)

    return g.compile(checkpointer=checkpointer)
