import pytest

from app.tools.data_tools import ToolError, get_column_values, run_probe_query


def test_column_values_most_frequent_first(catalog, db_path):
    result = get_column_values(catalog, db_path, "Customers", "State")
    assert result["values"][0] == {"value": "California", "count": 4}
    assert not result["truncated"]


def test_column_values_search_is_case_insensitive(catalog, db_path):
    result = get_column_values(catalog, db_path, "customers", "state", search="CALI")
    assert result["table"] == "Customers" and result["column"] == "State"
    assert [v["value"] for v in result["values"]] == ["California"]


def test_column_values_limit(catalog, db_path):
    result = get_column_values(catalog, db_path, "Employees", "LastName", limit=3)
    assert len(result["values"]) == 3 and result["truncated"]


def test_search_wildcards_are_literal(catalog, db_path):
    assert get_column_values(catalog, db_path, "Customers", "State", search="%")["values"] == []


def test_search_is_parameterised(catalog, db_path):
    result = get_column_values(catalog, db_path, "Customers", "State", search="' OR 1=1 --")
    assert result["values"] == []


def test_unknown_table_and_column(catalog, db_path):
    with pytest.raises(ToolError, match="Unknown table 'Invoices'. Available: Customers"):
        get_column_values(catalog, db_path, "Invoices", "Id")
    with pytest.raises(ToolError, match="Unknown column 'Region' in Customers"):
        get_column_values(catalog, db_path, "Customers", "Region")


def test_injection_through_identifier_is_impossible(catalog, db_path):
    with pytest.raises(ToolError):
        get_column_values(catalog, db_path, "Customers; DROP TABLE Orders", "State")


def test_probe_query(catalog, db_path):
    result = run_probe_query(catalog, db_path, "SELECT MIN(HireDate), MAX(HireDate) FROM Employees")
    assert result["rows"] == [["2018-07-01", "2025-02-18"]]


def test_probe_query_row_cap(catalog, db_path):
    result = run_probe_query(catalog, db_path, "SELECT * FROM OrderItems", max_rows=20)
    assert len(result["rows"]) == 19 and not result["truncated"]
    assert run_probe_query(catalog, db_path, "SELECT * FROM OrderItems", max_rows=10)["truncated"]


def test_probe_query_is_validated(catalog, db_path):
    with pytest.raises(ToolError, match="Probe query rejected: .*read-only"):
        run_probe_query(catalog, db_path, "DROP TABLE Orders")
    with pytest.raises(ToolError, match="Unknown table"):
        run_probe_query(catalog, db_path, "SELECT * FROM sqlite_master")
