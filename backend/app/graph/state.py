"""Graph state.

`messages` is the user-visible conversation (human turns and final assistant
answers) and persists across turns via the checkpointer, together with
`last_sql`. Everything else is per-turn working state, reset by `input_guard`.
"""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Persisted across turns
    messages: Annotated[list[AnyMessage], add_messages]
    last_sql: str | None

    # Per-turn
    user_input: str
    intent: str
    task: str
    input_sql: str | None
    clarification: str | None
    schema_context: str
    scratchpad: list[AnyMessage]      # generator's tool-calling conversation for this turn
    tool_calls: int
    tool_log: list[dict[str, Any]]    # data lookups, shown in the UI
    retries: int
    sql: str | None
    assumptions: list[str]
    notes: list[str]
    validation_errors: list[str]
    validation_warnings: list[str]
    optimization: dict[str, Any] | None
    explanation: str | None
    response: dict[str, Any]          # final payload returned to the API
