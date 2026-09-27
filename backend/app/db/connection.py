"""Read-only SQLite connections with a time limit."""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# How many SQLite VM instructions run between progress-handler checks.
_PROGRESS_INTERVAL = 1000


class QueryTimeoutError(Exception):
    pass


@contextmanager
def readonly_connection(db_path: Path, timeout_seconds: float = 5.0) -> Iterator[sqlite3.Connection]:
    """Open `db_path` so that no statement can modify it.

    Two independent layers: the file is opened with `mode=ro`, and
    `PRAGMA query_only` makes SQLite reject writes on this connection.
    Statements running longer than `timeout_seconds` are interrupted.
    """
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
    try:
        conn.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + timeout_seconds
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), _PROGRESS_INTERVAL)
        try:
            yield conn
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e):
                raise QueryTimeoutError(f"Query exceeded the {timeout_seconds:g}s time limit") from e
            raise
    finally:
        conn.close()
