import sqlite3

import pytest

from app.db.connection import QueryTimeoutError, readonly_connection
from app.runner.runner import QueryRejectedError, execute_query


def test_executes_select(catalog, db_path):
    result = execute_query(
        "SELECT FirstName, LastName FROM Employees WHERE HireDate >= '2024-01-01' ORDER BY HireDate",
        catalog, db_path,
    )
    assert result.columns == ["FirstName", "LastName"]
    assert len(result.rows) == 6
    assert result.rows[0] == ["Grace", "Patel"]
    assert not result.truncated


def test_follow_up_example_from_brief(catalog, db_path):
    result = execute_query("SELECT * FROM Customers WHERE State = 'California'", catalog, db_path)
    assert len(result.rows) == 4


def test_truncates_at_max_rows(catalog, db_path):
    result = execute_query("SELECT * FROM OrderItems", catalog, db_path, max_rows=5)
    assert len(result.rows) == 5
    assert result.truncated


def test_rejects_invalid_sql_before_running(catalog, db_path):
    with pytest.raises(QueryRejectedError) as exc:
        execute_query("DELETE FROM Orders", catalog, db_path)
    assert "read-only" in exc.value.errors[0]


def test_rejects_unknown_function(catalog, db_path):
    with pytest.raises(QueryRejectedError, match="no such function"):
        execute_query("SELECT no_such_function(Name) FROM Products", catalog, db_path)


def test_returns_validation_warnings(catalog, db_path):
    result = execute_query("SELECT * FROM Orders o JOIN Customers c ON o.EmployeeID = c.CustomerID", catalog, db_path)
    assert result.warnings


def test_connection_cannot_write_even_without_validation(db_path):
    # Defense in depth: bypass the validator entirely and try to write.
    with readonly_connection(db_path) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM Orders")
    with sqlite3.connect(db_path) as check:
        assert check.execute("SELECT COUNT(*) FROM Orders").fetchone()[0] == 12


def test_timeout_interrupts_long_query(catalog, db_path):
    runaway = (
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) "
        "SELECT COUNT(*) FROM n JOIN Orders ON 1 = 1"
    )
    with pytest.raises(QueryTimeoutError):
        execute_query(runaway, catalog, db_path, timeout_seconds=0.2)
