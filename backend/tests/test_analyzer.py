import pytest

from app.optimization.analyzer import analyze_query, format_sql


def analyze(sql, catalog, conn):
    return analyze_query(sql, catalog, conn)


def test_recommends_index_for_scanned_filter_column(catalog, conn):
    report = analyze("SELECT FirstName FROM Employees WHERE HireDate >= '2024-01-01'", catalog, conn)
    assert report.plan == ["SCAN Employees"]
    assert report.index_recommendations == ["CREATE INDEX idx_employees_hiredate ON Employees(HireDate);"]


def test_recommends_index_when_scan_uses_unrelated_index(catalog, conn):
    report = analyze(
        "SELECT CustomerID, SUM(TotalAmount) FROM Orders WHERE Status = 'Shipped' GROUP BY CustomerID",
        catalog, conn,
    )
    assert "CREATE INDEX idx_orders_status ON Orders(Status);" in report.index_recommendations


def test_no_index_advice_for_indexed_or_primary_key_columns(catalog, conn):
    assert analyze("SELECT * FROM Orders WHERE CustomerID = 3", catalog, conn).index_recommendations == []
    assert analyze("SELECT * FROM Employees WHERE EmployeeID = 3", catalog, conn).index_recommendations == []


def test_flags_select_star(catalog, conn):
    assert any("SELECT *" in s for s in analyze("SELECT * FROM Products", catalog, conn).suggestions)


def test_flags_function_on_filtered_column(catalog, conn):
    report = analyze("SELECT FirstName FROM Employees WHERE strftime('%Y', HireDate) = '2024'", catalog, conn)
    assert any("STRFTIME('%Y', HireDate)" in s for s in report.suggestions)


def test_flags_leading_wildcard(catalog, conn):
    report = analyze("SELECT Email FROM Customers WHERE Email LIKE '%@example.com'", catalog, conn)
    assert any("starts with a wildcard" in s for s in report.suggestions)


def test_flags_unused_left_join(catalog, conn):
    report = analyze(
        "SELECT e.FirstName FROM Employees e LEFT JOIN Departments d ON e.DepartmentID = d.DepartmentID",
        catalog, conn,
    )
    assert "The join to Departments contributes no columns; it cannot change the result and can be removed." in report.suggestions


def test_unused_left_join_on_non_unique_key_may_duplicate(catalog, conn):
    report = analyze(
        "SELECT c.FirstName FROM Customers c LEFT JOIN Orders o ON o.CustomerID = c.CustomerID",
        catalog, conn,
    )
    assert any("Orders contributes no columns; it may duplicate rows" in s for s in report.suggestions)


def test_used_join_is_not_flagged(catalog, conn):
    report = analyze(
        "SELECT e.FirstName, d.Name FROM Employees e JOIN Departments d ON e.DepartmentID = d.DepartmentID",
        catalog, conn,
    )
    assert not any("contributes no columns" in s for s in report.suggestions)


def test_cost_estimate(catalog, conn):
    cost = analyze("SELECT FirstName FROM Employees WHERE Salary > 100000", catalog, conn).cost
    assert cost == {"level": "low", "full_scans": ["Employees"], "rows_scanned_estimate": 15, "uses_temp_sort": False}


def test_transpiles_to_other_dialects(catalog, conn):
    dialects = analyze("SELECT FirstName FROM Customers ORDER BY CreatedAt DESC LIMIT 5", catalog, conn).dialects
    assert set(dialects) == {"sqlite", "postgres", "mysql"}
    assert "LIMIT 5" in dialects["postgres"]


def test_format_sql():
    assert format_sql("select a from t where b=1") == "SELECT\n  a\nFROM t\nWHERE\n  b = 1"


@pytest.mark.parametrize("sql", [
    "WITH t AS (SELECT CustomerID, SUM(TotalAmount) s FROM Orders GROUP BY CustomerID) "
    "SELECT c.FirstName, t.s FROM t JOIN Customers c ON c.CustomerID = t.CustomerID",
    "SELECT Name FROM Products WHERE ProductID IN (SELECT ProductID FROM OrderItems WHERE Quantity > 1)",
    "SELECT City FROM Customers UNION SELECT Location FROM Departments",
])
def test_handles_complex_queries(sql, catalog, conn):
    report = analyze(sql, catalog, conn)
    assert report.formatted_sql and report.plan
