"""Structured-output and tool schemas the LLM sees."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal[
    "generate", "follow_up", "optimize", "debug", "explain_sql",
    "schema_question", "destructive", "out_of_scope", "ambiguous",
]


class IntentClassification(BaseModel):
    """Classification of the user's latest message."""

    intent: Intent
    task: str = Field(description="The request restated as one standalone instruction.")
    user_sql: str | None = Field(default=None, description="SQL supplied by the user, verbatim.")
    clarification_question: str | None = Field(
        default=None, description="For ambiguous requests only: one short question for the user."
    )


class GetColumnValues(BaseModel):
    """Look up the distinct values stored in a column, most frequent first.

    Use before filtering on text values to learn exactly how they are stored.
    """

    model_config = ConfigDict(title="get_column_values")

    table: str = Field(description="Table name from the schema.")
    column: str = Field(description="Column name in that table.")
    search: str | None = Field(
        default=None, description="Optional case-insensitive substring to filter values, e.g. 'cali'."
    )


class RunProbeQuery(BaseModel):
    """Run a small read-only SELECT to learn a fact about the data (at most 20 rows returned),
    e.g. `SELECT MIN(HireDate), MAX(HireDate) FROM Employees`. Not for answering the user."""

    model_config = ConfigDict(title="run_probe_query")

    sql: str = Field(description="A single SQLite SELECT statement.")


class SubmitSQL(BaseModel):
    """Submit the final SQL query. It is validated; fix any reported errors and submit again."""

    model_config = ConfigDict(title="submit_sql")

    sql: str = Field(description="One read-only SQLite SELECT statement.")
    assumptions: list[str] = Field(
        default_factory=list,
        description="Interpretations you made, e.g. 'top customers means highest total order amount'.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="For debugging: each issue found and why. For optimizing: each change and why.",
    )


class CannotAnswer(BaseModel):
    """Use when the request cannot be answered with the available schema."""

    model_config = ConfigDict(title="cannot_answer")

    reason: str = Field(description="What is missing from the schema, in plain language.")


DATA_TOOLS = [GetColumnValues, RunProbeQuery]
FINAL_TOOLS = [SubmitSQL, CannotAnswer]
