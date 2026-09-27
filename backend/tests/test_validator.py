import pytest

from app.validation.validator import validate_sql


def errors(sql, catalog, conn=None):
    return validate_sql(sql, catalog, conn).errors


# --- valid queries -----------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM Employees WHERE HireDate >= '2024-01-01'",
    "select firstname, lastname from employees",
    "SELECT * FROM Customers WHERE State = 'California';",
    "SELECT d.Name, COUNT(*) AS headcount FROM Employees e "
    "JOIN Departments d ON e.DepartmentID = d.DepartmentID GROUP BY d.Name ORDER BY headcount DESC",
    "WITH totals AS (SELECT CustomerID, SUM(TotalAmount) AS spent FROM Orders GROUP BY CustomerID) "
    "SELECT c.FirstName, t.spent FROM Customers c JOIN totals t ON t.CustomerID = c.CustomerID",
    "SELECT Name FROM Products WHERE ProductID IN (SELECT ProductID FROM OrderItems)",
    "SELECT City FROM Customers UNION SELECT Location FROM Departments",
    "SELECT e.FirstName, m.FirstName AS Manager FROM Employees e LEFT JOIN Employees m ON e.ManagerID = m.EmployeeID",
    "SELECT strftime('%Y', OrderDate) AS yr, SUM(TotalAmount) FROM Orders GROUP BY yr",
])
def test_valid_queries(sql, catalog, conn):
    result = validate_sql(sql, catalog, conn)
    assert result.is_valid, result.errors


def test_reports_tables_used(catalog):
    result = validate_sql("SELECT * FROM orders o JOIN customers c ON o.CustomerID = c.CustomerID", catalog)
    assert result.tables == ["Orders", "Customers"]


def test_normalises_trailing_semicolon(catalog):
    assert validate_sql("SELECT * FROM Orders;  ", catalog).sql == "SELECT * FROM Orders"


# --- read-only enforcement ---------------------------------------------------

@pytest.mark.parametrize("sql, keyword", [
    ("DELETE FROM Employees", "DELETE"),
    ("UPDATE Employees SET Salary = 0", "UPDATE"),
    ("INSERT INTO Departments VALUES (9, 'X', 'Y', 1)", "INSERT"),
    ("DROP TABLE Employees", "DROP"),
    ("ALTER TABLE Employees ADD COLUMN x TEXT", "ALTER"),
    ("CREATE TABLE x (id INTEGER)", "CREATE"),
    ("WITH d AS (DELETE FROM Orders RETURNING *) SELECT * FROM d", "DELETE"),
])
def test_rejects_writes(sql, keyword, catalog):
    errs = errors(sql, catalog)
    assert len(errs) == 1
    assert "read-only" in errs[0] and keyword in errs[0]


@pytest.mark.parametrize("sql", [
    "PRAGMA table_info(Employees)",
    "ATTACH DATABASE 'other.db' AS other",
    "VACUUM",
    "REINDEX",
    "REPLACE INTO Departments VALUES (1, 'X', 'Y', 1)",
    "BEGIN TRANSACTION",
    "EXPLAIN SELECT * FROM Employees",
])
def test_rejects_non_query_statements(sql, catalog):
    errs = errors(sql, catalog)
    assert errs and "read-only" in errs[0]


def test_rejects_multiple_statements(catalog):
    errs = errors("SELECT * FROM Employees; DROP TABLE Employees", catalog)
    assert "Exactly one SQL statement" in errs[0]


def test_rejects_stacked_selects(catalog):
    assert "Exactly one SQL statement" in errors("SELECT 1 FROM Orders; SELECT 2 FROM Orders", catalog)[0]


# --- syntax ------------------------------------------------------------------

@pytest.mark.parametrize("sql", ["SELECT * FROM Employees WHERE", "SELEC * FROM Employees", "SELECT FROM"])
def test_rejects_syntax_errors(sql, catalog):
    errs = errors(sql, catalog)
    assert errs and errs[0].startswith("Syntax error")


def test_rejects_empty(catalog):
    assert errors("  ;  ", catalog) == ["The SQL query is empty."]


# --- hallucinated tables and columns -----------------------------------------

def test_unknown_table_with_suggestion(catalog):
    errs = errors("SELECT * FROM Employee", catalog)
    assert errs == ["Unknown table 'Employee'. Did you mean: Employees?"]


def test_unknown_table_in_join(catalog):
    errs = errors("SELECT * FROM Orders o JOIN Invoices i ON i.OrderID = o.OrderID", catalog)
    assert "Unknown table 'Invoices'" in errs[0]


def test_unknown_column_with_suggestion(catalog):
    errs = errors("SELECT HireDat FROM Employees", catalog)
    assert "Unknown column 'hiredat'" in errs[0]
    assert "Employees.HireDate" in errs[0]


def test_unknown_qualified_column(catalog):
    errs = errors("SELECT c.Region FROM Customers c", catalog)
    assert "Unknown column 'region'" in errs[0]


def test_column_from_wrong_table(catalog):
    errs = errors("SELECT Salary FROM Customers", catalog)
    assert "Unknown column 'salary'" in errs[0]


def test_ambiguous_column(catalog):
    errs = errors("SELECT CustomerID FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID", catalog)
    assert errs and "Ambiguous column 'customerid': it exists in Orders, Customers" in errs[0]


def test_other_schema_is_rejected(catalog):
    assert "outside the provided schema" in errors("SELECT * FROM other.Employees", catalog)[0]


def test_requires_a_schema_table(catalog):
    # Stops the agent being used as a calculator ("what is 2+2" -> SELECT 2+2).
    assert "does not reference any table" in errors("SELECT 2 + 2", catalog)[0]


def test_cte_names_are_not_treated_as_tables(catalog):
    result = validate_sql("WITH x AS (SELECT * FROM Orders) SELECT * FROM x", catalog)
    assert result.is_valid and result.tables == ["Orders"]


# --- relationships -----------------------------------------------------------

def test_foreign_key_join_has_no_warning(catalog):
    result = validate_sql(
        "SELECT * FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID", catalog
    )
    assert result.warnings == []


def test_warns_on_join_without_foreign_key(catalog):
    result = validate_sql(
        "SELECT * FROM Orders o JOIN Customers c ON o.EmployeeID = c.CustomerID", catalog
    )
    assert result.is_valid
    assert "Orders.EmployeeID = Customers.CustomerID does not follow a declared foreign key" in result.warnings[0]


def test_warns_on_join_without_condition(catalog):
    result = validate_sql("SELECT * FROM Orders JOIN Customers", catalog)
    assert "cross product" in result.warnings[0]


# --- engine check ------------------------------------------------------------

def test_engine_check_catches_what_parser_accepts(catalog, conn):
    # sqlglot parses an unknown function; SQLite refuses to compile it.
    result = validate_sql("SELECT no_such_function(Name) FROM Products", catalog, conn)
    assert "database rejected" in result.errors[0]
