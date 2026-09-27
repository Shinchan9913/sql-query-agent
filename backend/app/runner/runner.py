"""Execute validated, read-only queries.

Used by the user's "Run" button (`/api/execute`) and by the agent's probe tool.
SQL is always re-validated here: callers are not trusted to have done it.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.catalog import SchemaCatalog
from app.db.connection import readonly_connection
from app.validation.validator import validate_sql


class QueryRejectedError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: float
    warnings: list[str]


def execute_query(
    sql: str,
    catalog: SchemaCatalog,
    db_path: Path,
    max_rows: int = 500,
    timeout_seconds: float = 5.0,
) -> QueryResult:
    """Validate and run `sql`, returning at most `max_rows` rows.

    Rows are fetched incrementally, so the query itself is not rewritten to add a LIMIT.
    Raises QueryRejectedError if validation fails and QueryTimeoutError on timeout.
    """
    with readonly_connection(db_path, timeout_seconds) as conn:
        validation = validate_sql(sql, catalog, conn)
        if not validation.is_valid:
            raise QueryRejectedError(validation.errors)

        started = time.perf_counter()
        cursor = conn.execute(validation.sql)
        rows = cursor.fetchmany(max_rows + 1)
        elapsed_ms = (time.perf_counter() - started) * 1000

        return QueryResult(
            columns=[d[0] for d in cursor.description or []],
            rows=[list(r) for r in rows[:max_rows]],
            truncated=len(rows) > max_rows,
            elapsed_ms=round(elapsed_ms, 2),
            warnings=validation.warnings,
        )
