def test_loads_all_tables(catalog):
    assert {t.name for t in catalog.tables} == {
        "Customers", "Departments", "Employees", "OrderItems", "Orders", "Products",
    }


def test_lookup_is_case_insensitive(catalog):
    assert catalog.table("employees").name == "Employees"
    assert catalog.table("EMPLOYEES").column("hiredate").name == "HireDate"
    assert catalog.table("Nope") is None


def test_foreign_keys_and_relationships(catalog):
    fks = {(fk.column, fk.ref_table, fk.ref_column) for fk in catalog.table("Orders").foreign_keys}
    assert ("CustomerID", "Customers", "CustomerID") in fks
    assert catalog.relationship_exists("Orders", "CustomerID", "Customers", "CustomerID")
    assert catalog.relationship_exists("customers", "customerid", "orders", "customerid")
    assert not catalog.relationship_exists("Orders", "EmployeeID", "Customers", "CustomerID")


def test_self_referencing_foreign_key(catalog):
    assert catalog.relationship_exists("Employees", "ManagerID", "Employees", "EmployeeID")


def test_indexes(catalog):
    index_columns = {i.columns for i in catalog.table("Orders").indexes}
    assert ("CustomerID",) in index_columns


def test_prompt_contains_structure_only(catalog):
    prompt = catalog.to_prompt()
    assert "TABLE Employees (" in prompt
    assert "DepartmentID INTEGER NOT NULL REFERENCES Departments(DepartmentID)" in prompt
    assert "California" not in prompt  # no row data leaks into the schema context
