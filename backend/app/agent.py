"""Wires settings, schema catalog, LLM and checkpointer into a ready-to-use graph."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings, get_settings
from app.db.catalog import SchemaCatalog
from app.db.connection import readonly_connection
from app.graph.builder import build_graph
from app.llm import create_llm



def load_catalog(settings: Settings) -> SchemaCatalog:
    with readonly_connection(settings.resolved_database_path) as conn:
        return SchemaCatalog.from_connection(conn)


def create_agent(
    checkpointer: BaseCheckpointSaver | None = None, settings: Settings | None = None
) -> CompiledStateGraph:
    settings = settings or get_settings()
    return build_graph(
        create_llm(settings),
        load_catalog(settings),
        settings.resolved_database_path,
        settings,
        checkpointer,
    )


