"""Read-only data lookups the agent can use while writing SQL.

These are plain functions; the graph wraps them as LangChain tools. Each one
returns a JSON-serialisable dict, or raises ToolError with a message the model
can act on.
"""

from pathlib import Path
from typing import Any

from app.db.catalog import SchemaCatalog
from app.db.connection import QueryTimeoutError, readonly_connection
from app.runner.runner import QueryRejectedError, execute_query


class ToolError(Exception):
    pass


def get_column_values(
    catalog: SchemaCatalog,
    db_path: Path,
    table: str,
    column: str,
    search: str | None = None,
    limit: int = 25,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Distinct non-null values of `table.column`, most frequent first.

    `search` filters values with a case-insensitive substring match.
    """
    schema_table = catalog.table(table)
    if schema_table is None:
        raise ToolError(f"Unknown table '{table}'. Available: {', '.join(t.name for t in catalog.tables)}")
    schema_column = schema_table.column(column)
    if schema_column is None:
        raise ToolError(
            f"Unknown column '{column}' in {schema_table.name}. "
            f"Available: {', '.join(c.name for c in schema_table.columns)}"
        )

    # Identifiers come from the catalog, never from the model; values are bound parameters.
    col = _quote(schema_column.name)
    sql = f"SELECT {col}, COUNT(*) FROM {_quote(schema_table.name)} WHERE {col} IS NOT NULL"
    params: list[Any] = []
    if search:
        sql += f" AND CAST({col} AS TEXT) LIKE ? ESCAPE '\\'"
        params.append(f"%{_escape_like(search)}%")
    sql += f" GROUP BY {col} ORDER BY COUNT(*) DESC, {col} LIMIT ?"
    params.append(limit + 1)

    try:
        with readonly_connection(db_path, timeout_seconds) as conn:
            rows = conn.execute(sql, params).fetchall()
    except QueryTimeoutError as e:
        raise ToolError(str(e)) from e

    return {
        "table": schema_table.name,
        "column": schema_column.name,
        "search": search,
        "values": [{"value": v, "count": n} for v, n in rows[:limit]],
        "truncated": len(rows) > limit,
    }


def run_probe_query(
    catalog: SchemaCatalog,
    db_path: Path,
    sql: str,
    max_rows: int = 20,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Run a small exploratory SELECT (fully validated, capped rows)."""
    try:
        result = execute_query(sql, catalog, db_path, max_rows=max_rows, timeout_seconds=timeout_seconds)
    except QueryRejectedError as e:
        raise ToolError("Probe query rejected: " + " ".join(e.errors)) from e
    except QueryTimeoutError as e:
        raise ToolError(str(e)) from e

    return {
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
    }


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
